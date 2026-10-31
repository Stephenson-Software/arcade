// Prints HallWalk.resolve for each point, so tests/test_walks.py can check
// arcade.walks.resolve (its Python port) gives the same answers:
//   node tests/browser/hall_walk_parity.cjs <layout.json> <points.json>
const fs = require("fs");
const path = require("path");
const W = require(path.join(__dirname, "..", "..", "src", "arcade", "hall_assets", "hall-walk.js"));
const layout = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const points = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const world = W.world(layout);
process.stdout.write(JSON.stringify(points.map(([x, z]) => { const p = W.resolve(x, z, world); return [p.x, p.z]; })));
