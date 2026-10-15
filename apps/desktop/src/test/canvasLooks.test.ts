import { describe, expect, it } from "vitest";
import type { Act } from "../lib/acting";
import { drawLens, drawRunner, drawSwarm, lensGoal, newMemory, type World } from "../views/CanvasLooks";

// A 2D context that accepts every drawing call and does nothing.
const ctx = new Proxy({}, { get: () => () => undefined, set: () => true }) as unknown as CanvasRenderingContext2D;
const button = { x: 700, y: 400, width: 100, height: 30 };
const act: Act = { id: "s1", motion: "tap", kind: "element", rect: button, running: true };
const world = (over: Partial<World>): World => ({
  width: 1366, height: 768, home: { x: 683, y: 734 }, target: { x: 600, y: 200, width: 500, height: 300 },
  act: null, mood: "listen", reaction: null, level: 0.2, dodge: null, ...over,
});

describe("canvas looks act at the real spot", () => {
  it("the swarm outlines the control it is about to press", () => {
    const w = world({ mood: "work", act });
    const mem = newMemory(w.home);
    for (let f = 0; f < 240; f++) drawSwarm(ctx, w, mem, mem.t0 + f * 16);
    const near = mem.particles.filter((p) =>
      p.x > button.x - 30 && p.x < button.x + button.width + 30 && p.y > button.y - 30 && p.y < button.y + button.height + 30);
    expect(near.length).toBeGreaterThan(mem.particles.length * 0.8);
  });

  it("the swarm scatters from a slowing cursor", () => {
    const w = world({ mood: "think", dodge: { x: 683, y: 674 } });
    const mem = newMemory(w.home);
    for (let f = 0; f < 200; f++) drawSwarm(ctx, w, mem, mem.t0 + f * 16);
    const close = mem.particles.filter((p) => Math.hypot(p.x - 683, p.y - 674) < 40);
    expect(close.length).toBeLessThan(5);
  });

  it("the runner reaches the target within the travel budget, and acts at home without one", () => {
    const w = world({ mood: "work", act, home: { x: 650, y: 200 } });
    const mem = newMemory(w.home);
    drawRunner(ctx, world({ mood: "think", home: { x: 650, y: 200 } }), mem, mem.t0);
    drawRunner(ctx, w, mem, mem.t0 + 16);
    drawRunner(ctx, w, mem, mem.t0 + 16 + 430);
    expect(Math.abs((mem.at?.x ?? 0) - (button.x + button.width / 2))).toBeLessThan(2);
    expect(Math.abs((mem.at?.y ?? 0) - button.y)).toBeLessThan(2);
    const noStage = world({ mood: "work", act: { ...act, rect: null }, home: { x: 650, y: 200 } });
    drawRunner(ctx, noStage, mem, mem.t0 + 2000);
    drawRunner(ctx, noStage, mem, mem.t0 + 2500);
    expect(mem.at?.x).toBeCloseTo(650, 0); // never a guessed position
  });

  it("the lens settles over the control it presses and leaves when done", () => {
    const mem = newMemory({ x: 683, y: 672 });
    const goal = lensGoal(world({ mood: "work", act }), mem, mem.t0 + 100);
    expect(goal.x).toBe(button.x + button.width / 2);
    expect(goal.y).toBe(button.y + button.height / 2);
    const w = world({ mood: "away" });
    for (let f = 0; f < 120; f++) drawLens(ctx, w, mem, mem.t0 + f * 16, true);
    expect(mem.r).toBeLessThan(2);
  });
});
