"""HTTP boundary for the local researcher application."""
import base64
from contextlib import asynccontextmanager
from io import BytesIO
from pathlib import Path
import threading
import uuid

from fastapi import FastAPI, HTTPException, BackgroundTasks, Query
from fastapi.responses import FileResponse, PlainTextResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from circuit_ingest.networkx_graph import build_networkx_graph
from .catalog import Catalog, RevisionConflict, UserMetadata
from .uploads import parse_upload
from .retrieval import Retrieval, port_role
from .neo4j import Neo4jService
from .settings import Settings

STATIC = Path(__file__).parent / "static"


class EditRequest(BaseModel):
    revision: int = Field(ge=0)
    metadata: UserMetadata


class UploadRequest(BaseModel):
    netlist: str = Field(max_length=1_000_000)
    description: str = Field(min_length=1, max_length=6000)
    ports: str = Field(default="", max_length=20000)
    metadata: UserMetadata = Field(default_factory=UserMetadata)
    image_base64: str = Field(default="", max_length=8_000_000)


class CypherRequest(BaseModel):
    query: str = Field(min_length=1, max_length=20000)
    parameters: dict = Field(default_factory=dict)
    limit: int = Field(default=200, ge=1, le=1000)


class SearchRequest(BaseModel):
    text: str = Field(default="", max_length=6000)
    reference_id: str = Field(default="", max_length=200)
    limit: int = Field(default=20, ge=1, le=100)
    dataset: str = Field(default="", max_length=100)
    device: str = Field(default="", max_length=40)
    family: str = Field(default="", max_length=100)


def create_app(settings=None, background=True):
    settings = settings or Settings.local()
    catalog = Catalog(settings.state, settings.corpus, settings.upstream)
    retrieval = Retrieval(catalog)
    neo = Neo4jService(settings, catalog)
    stopped = threading.Event()

    def worker():
        neo.health()
        retrieval.build_safe()
        while not stopped.is_set():
            neo.sync()
            stopped.wait(20)

    def changed(identifier):
        try:
            retrieval.update(identifier)
        except ValueError:
            pass
        neo.sync()

    @asynccontextmanager
    async def lifespan(app):
        if background:
            threading.Thread(target=worker, daemon=True, name="circuit-indexer").start()
        yield
        stopped.set()
        neo.driver.close()

    app = FastAPI(title="Circuit Atlas", lifespan=lifespan)
    app.state.catalog, app.state.retrieval, app.state.neo4j = catalog, retrieval, neo
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])

    @app.middleware("http")
    async def same_origin(request, call_next):
        origin = request.headers.get("origin")
        if request.method not in {"GET", "HEAD", "OPTIONS"} and origin and origin != str(request.base_url).rstrip("/"):
            return JSONResponse({"detail": "Use the local workbench to make changes."}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(KeyError)
    async def missing(request, exc):
        return JSONResponse({"detail": "Circuit not found."}, status_code=404)

    @app.exception_handler(RevisionConflict)
    async def conflict(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.get("/api/status")
    def status():
        with catalog.connect() as db:
            count = db.execute("SELECT count(*) FROM circuits").fetchone()[0]
            vectors = db.execute("SELECT count(*) FROM vectors v JOIN circuits c ON c.id=v.id AND c.revision=v.revision WHERE v.semantic IS NOT NULL").fetchone()[0]
            pending = db.execute("SELECT count(*) FROM circuits WHERE sync_state!='synced'").fetchone()[0]
            edited = db.execute("SELECT count(*) FROM circuits WHERE revision>0").fetchone()[0]
        return {"application": "circuit-atlas", "project": str(settings.root.resolve()),
                "circuits": count, "edited": edited, "indexed": vectors,
                "retrieval": retrieval.status, "neo4j": {**neo.state, "pending": pending}}

    @app.get("/api/circuits")
    def circuits(search: str = "", dataset: str = "", device: str = "", family: str = "",
                 offset: int = Query(0, ge=0), limit: int = Query(40, ge=1, le=100)):
        return catalog.list(search, dataset, device, family, offset, limit)

    @app.get("/api/circuits/{identifier}")
    def detail(identifier: str):
        result = catalog.detail(identifier)
        with catalog.connect() as db:
            v = db.execute("SELECT v.semantic,v.error FROM vectors v JOIN circuits c ON c.id=v.id AND c.revision=v.revision WHERE v.id=?", (identifier,)).fetchone()
        result["embedding_state"] = "ready" if v and v["semantic"] else "pending"
        result["embedding_error"] = v["error"] if v else ""
        return result

    @app.patch("/api/circuits/{identifier}")
    def edit(identifier: str, request: EditRequest, tasks: BackgroundTasks):
        result = catalog.edit(identifier, request.metadata.model_dump(), request.revision)
        if background:
            tasks.add_task(changed, identifier)
        return result

    @app.get("/api/circuits/{identifier}/graph")
    def graph(identifier: str, backend: str = "networkx"):
        catalog.row(identifier)
        if backend == "neo4j":
            try:
                return {**neo.graph(identifier), "backend": "neo4j"}
            except ValueError:
                raise
            except Exception as exc:
                raise HTTPException(503, "Neo4j is unavailable. NetworkX remains available.") from exc
        if backend != "networkx":
            raise HTTPException(422, "Choose networkx or neo4j.")
        g = build_networkx_graph(catalog.record(identifier))
        nodes = []
        for identifier, props in g.nodes(data=True):
            label = props.get("source_instance") or props.get("name") or identifier
            role = port_role(props.get("name", "")) if props["kind"] in {"Net", "Port"} else ""
            nodes.append({"id": identifier, "canonical_id": identifier, "kind": props["kind"], "label": label, "properties": props, "role": role})
        edges = [{"id": f"{a}|{b}|{key}", "from": a, "to": b, "label": p.get("terminal", p["kind"]), "kind": p["kind"], "properties": p}
                 for a, b, key, p in g.edges(keys=True, data=True)]
        return {"nodes": nodes, "edges": edges, "backend": "networkx"}

    @app.get("/api/circuits/{identifier}/record")
    def record(identifier: str):
        return JSONResponse(catalog.record(identifier).model_dump(mode="json"), headers={"Content-Disposition": 'attachment; filename="circuit.json"'})

    @app.get("/api/circuits/{identifier}/networkx")
    def networkx_export(identifier: str):
        import networkx as nx
        graph = build_networkx_graph(catalog.record(identifier))
        return JSONResponse(nx.node_link_data(graph, edges="edges"),
                            headers={"Content-Disposition": 'attachment; filename="circuit.networkx.json"'})

    @app.get("/api/circuits/{identifier}/netlist")
    def netlist(identifier: str):
        row = catalog.row(identifier)
        return PlainTextResponse(row["netlist"], headers={"Content-Disposition": 'attachment; filename="circuit.cir"'})

    @app.get("/api/circuits/{identifier}/asset/{kind}")
    def asset(identifier: str, kind: str):
        path = catalog.asset(identifier, kind)
        if not path:
            raise HTTPException(404, "No schematic available for this circuit.")
        return FileResponse(path)

    @app.post("/api/uploads/preview")
    def preview(request: UploadRequest):
        record = parse_upload(request.netlist, request.description, request.ports)
        return {"statistics": record.statistics.model_dump(), "ports": [p.name for p in record.ports],
                "net_names": [n.name for n in record.nets], "warnings": ["No ports supplied. Add external signal and supply nets for better structural retrieval."] if not record.ports else []}

    @app.post("/api/uploads", status_code=201)
    def upload(request: UploadRequest, tasks: BackgroundTasks):
        record = parse_upload(request.netlist, request.description, request.ports)
        metadata = request.metadata.model_dump()
        metadata["description"] = request.description.strip()
        image_name, image_path = "", None
        if request.image_base64:
            from PIL import Image
            try:
                image_bytes = base64.b64decode(request.image_base64.split(",")[-1], validate=True)
                image = Image.open(BytesIO(image_bytes))
                if image.format not in {"PNG", "JPEG"} or image.width * image.height > 25_000_000:
                    raise ValueError("Use a PNG/JPEG schematic under 25 megapixels.")
                image.verify()
            except Exception as exc:
                raise ValueError("The schematic must be a valid PNG/JPEG image under 6 MB.") from exc
            image_name = str(uuid.uuid4()) + (".png" if image.format == "PNG" else ".jpg")
            image_path = catalog.state / "uploads" / image_name
            image_path.parent.mkdir(exist_ok=True)
            image_path.write_bytes(image_bytes)
        try:
            identifier = catalog.add_upload(record, request.netlist, metadata, image_name)
        except Exception:
            if image_path:
                image_path.unlink(missing_ok=True)
            raise
        if background:
            tasks.add_task(changed, identifier)
        return {"id": identifier, "sync_state": "pending", "statistics": record.statistics.model_dump()}

    @app.post("/api/query")
    def query(request: CypherRequest):
        from .neo4j import validate_cypher
        validate_cypher(request.query)
        try:
            result = neo.query(request.query, request.parameters, request.limit)
        except ValueError:
            raise
        except Exception as exc:
            # Preserve Neo4j's source-located syntax diagnostic, without credentials.
            message = getattr(exc, "message", None)
            raise HTTPException(422 if message else 503, message or "Neo4j is unavailable. Check its connection status.") from exc
        result["circuits"] = []
        for identifier in result["circuit_ids"]:
            try:
                result["circuits"].append(catalog.summary(catalog.row(identifier)))
            except KeyError:
                pass
        catalog.save_history("cypher", request.query, request.parameters, len(result["rows"]))
        return result

    @app.post("/api/search")
    def search(request: SearchRequest):
        result = retrieval.search(**request.model_dump())
        catalog.save_history("similarity", request.text or request.reference_id, request.model_dump(), len(result["items"]))
        return result

    @app.get("/api/history")
    def history():
        return catalog.history()

    @app.post("/api/reindex")
    def reindex(tasks: BackgroundTasks):
        if retrieval.status["state"] not in {"starting", "topology", "embedding"}:
            tasks.add_task(retrieval.build_safe)
        return {"status": "queued"}

    @app.post("/api/sync")
    def sync(tasks: BackgroundTasks):
        tasks.add_task(neo.sync)
        return {"status": "queued"}

    if STATIC.is_dir():
        app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/")
    def home():
        return FileResponse(STATIC / "index.html")

    return app
