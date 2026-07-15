// Vitest setup — jsdom + jest-dom matchers (toBeInTheDocument, etc).
import '@testing-library/jest-dom/vitest';

// jsdom implements neither a real 2-D canvas nor `Path2D`. The engine tests stub `getContext` with a
// no-op context, but the viewer's render loop constructs `new Path2D()` for its vector chrome (the
// unverified-outline batch, the reticle brackets). A stray `requestAnimationFrame` firing during a test
// then throws "Path2D is not defined" as an UNHANDLED error — the paint result is irrelevant to the
// contract the tests assert (that is Playwright's pixel job, §3.5), so a constructable no-op stub is the
// honest fix: it lets the paint calls complete without pretending to draw anything.
if (typeof globalThis.Path2D === 'undefined') {
  class Path2DStub {
    addPath(): void {}
    closePath(): void {}
    moveTo(): void {}
    lineTo(): void {}
    bezierCurveTo(): void {}
    quadraticCurveTo(): void {}
    arc(): void {}
    arcTo(): void {}
    ellipse(): void {}
    rect(): void {}
    roundRect(): void {}
  }
  globalThis.Path2D = Path2DStub as unknown as typeof Path2D;
}
