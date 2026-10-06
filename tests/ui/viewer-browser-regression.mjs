/** Run with the documented CUA tab binding against the local workbench.
 * The second query should take long enough to expand the previous graph and
 * return zero rows. The tested strict three-stage query is suitable locally.
 */
export async function verifyPendingQueryReplacesExpandedGraph(tab, slowEmptyQuery) {
  const close = tab.playwright.getByRole('button', {name:'Close expanded viewer'});
  if (await close.count()) await close.click();
  await tab.getAXState({emit:false});
  await tab.playwright.getByLabel('Cypher query', {exact:true}).fill(
    "MATCH (c:Circuit {id:'analoggenie:1004'})-[:HAS_DEVICE]->(d)\nMATCH (d)-[r:CONNECTED_TO]->(n:Net)\nRETURN d,r,n LIMIT 100"
  );
  await tab.playwright.getByRole('button', {name:'Run query →',exact:true}).click();
  await tab.playwright.locator('#run-query:not([disabled])').waitFor({state:'attached',timeoutMs:20000});
  await tab.playwright.getByRole('button', {name:'Graph · 32',exact:true}).waitFor({state:'visible'});
  await tab.getAXState({emit:false});
  await tab.playwright.getByRole('button', {name:'Graph · 32',exact:true}).click();
  await tab.getAXState({emit:false});
  await tab.playwright.getByLabel('Cypher query', {exact:true}).fill(slowEmptyQuery);
  await tab.playwright.getByRole('button', {name:'Run query →',exact:true}).click();
  await tab.playwright.getByRole('button', {name:'Expand viewer',exact:true}).click();
  await tab.getAXState({emit:false});
  await tab.playwright.locator('#run-query:not([disabled])').waitFor({state:'attached',timeoutMs:20000});
  const state = await tab.playwright.evaluate(() => ({
    dialogOpen:document.querySelector('#viewer-dialog').open,
    oldGraphPresent:!!document.querySelector('#viewer-dialog #result-graph'),
    result:document.querySelector('#query-result h2').textContent,
    bodyLocked:document.body.classList.contains('viewer-open'),
  }));
  if (state.result !== '0 rows returned') throw new Error('The diagnostic query did not finish with zero rows: '+JSON.stringify(state));
  if (state.dialogOpen || state.oldGraphPresent || state.bodyLocked) {
    throw new Error('New query results must dismiss and dispose the earlier expanded graph: '+JSON.stringify(state));
  }
  return state;
}

/** Catch a fixed/min-height canvas that pushes its controls below the window. */
export async function verifyDetailsFitViewport(tab) {
  const state = await tab.playwright.evaluate(() => {
    const viewer = document.querySelector('#detail-panel');
    const canvas = viewer?.querySelector('.graph-wrap,.schematic-viewport,.code-block');
    const footer = document.querySelector('.app-footer');
    return {
      viewportHeight:innerHeight,viewportWidth:innerWidth,
      pageHeight:document.scrollingElement.scrollHeight,
      pageWidth:document.scrollingElement.scrollWidth,
      viewerBottom:viewer?.getBoundingClientRect().bottom,
      footerBottom:footer.getBoundingClientRect().bottom,
      canvasHeight:canvas?.clientHeight,
    };
  });
  if (state.pageHeight > state.viewportHeight + 1 || state.pageWidth > state.viewportWidth + 1
      || state.viewerBottom > state.viewportHeight || state.footerBottom > state.viewportHeight + 1
      || !(state.canvasHeight >= 180)) {
    throw new Error('Circuit viewer and controls must fit the window without page scrolling: '+JSON.stringify(state));
  }
  return state;
}

/** The mobile metadata form must retain its intrinsic height in its scroller. */
export async function verifyMetadataFlow(tab) {
  const state = await tab.playwright.evaluate(() => {
    const layout = document.querySelector('.metadata-layout');
    return {
      formBottom:layout.querySelector('form').getBoundingClientRect().bottom,
      sourceTop:layout.querySelector('aside').getBoundingClientRect().top,
      saveBottom:layout.querySelector('button[type="submit"]').getBoundingClientRect().bottom,
      pageHeight:document.scrollingElement.scrollHeight,
      viewportHeight:innerHeight,
    };
  });
  if (state.sourceTop < state.formBottom || state.sourceTop < state.saveBottom
      || state.pageHeight > state.viewportHeight + 1) {
    throw new Error('Metadata must scroll inside its panel without overlapping source information: '+JSON.stringify(state));
  }
  return state;
}

/** Library rows should stay aligned after removing the redundant type-profile column. */
export async function verifyLibraryColumns(tab) {
  const state = await tab.playwright.evaluate(() => ({
    headers: [...document.querySelectorAll('.library-table th')].map(node => node.textContent.trim()),
    cellCounts: [...document.querySelectorAll('.library-table tbody tr')].map(row => row.cells.length),
    profileCells: document.querySelectorAll('.library-table .type-profile').length,
  }));
  if (JSON.stringify(state.headers) !== JSON.stringify(['CIRCUIT','DEVICES','NETS','SOURCE',''])
      || !state.cellCounts.length || state.cellCounts.some(count => count !== 5) || state.profileCells) {
    throw new Error('Library should show aligned identity/count/source columns, without Device profile: '+JSON.stringify(state));
  }
  return state;
}
