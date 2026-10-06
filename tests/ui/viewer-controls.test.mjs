import test from 'node:test';
import assert from 'node:assert/strict';
import {nextZoomScale, fitImageScale} from '../../src/circuit_workbench/static/viewer-controls.mjs';

// Catch additive zoom, swapped directions, missing bounds and NaN scale propagation.
test('zoom advances proportionally and reverses one step', () => {
  assert.equal(nextZoomScale(1, 1), 1.2);
  assert.equal(nextZoomScale(1.2, -1), 1);
  assert.equal(nextZoomScale(0.5, 1), 0.6);
});
test('repeated zoom never escapes the usable range', () => {
  let scale = 1;
  for (let i = 0; i < 100; i++) scale = nextZoomScale(scale, 1);
  assert.equal(scale, 4);
  for (let i = 0; i < 100; i++) scale = nextZoomScale(scale, -1);
  assert.equal(scale, 0.08);
});
test('unready or invalid current scales recover without NaN', () => {
  for (const value of [undefined, NaN, Infinity, 0, -2]) {
    assert.equal(nextZoomScale(value, 1), 1.2);
  }
  assert.equal(nextZoomScale(1, 0), 1);
});
// Catch fit implementations that use only width, upscale images, or ignore toolbar padding.
test('schematic fit respects both axes and never enlarges the original', () => {
  assert.equal(fitImageScale(1000, 500, 548, 548), 0.5);
  assert.equal(fitImageScale(500, 1000, 548, 548), 0.5);
  assert.equal(fitImageScale(100, 100, 548, 548), 1);
  assert.equal(fitImageScale(1000, 500, 1048, 298), 0.5);
});
test('unloaded or temporarily zero-size schematics produce a safe scale', () => {
  assert.equal(fitImageScale(0, 0, 548, 548), 1);
  assert.equal(fitImageScale(1000, 500, 0, 0), 0.08);
});
