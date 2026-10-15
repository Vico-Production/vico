import "@testing-library/jest-dom/vitest";

// jsdom has no canvas: the canvas looks draw nothing in tests (their logic is tested directly).
HTMLCanvasElement.prototype.getContext = (() => null) as unknown as HTMLCanvasElement["getContext"];
