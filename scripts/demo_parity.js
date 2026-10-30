// Runs the browser demo's logic on the sample and checks it matches the Python package.
// Usage: python -m meetingmind analyze samples/weekly_sync.txt > py.json && node scripts/demo_parity.js py.json
const fs = require("fs");
const html = fs.readFileSync(__dirname + "/../docs/index.html", "utf8");
const js = html.split("<script>")[1].split("</script>")[0];
const els = {};
global.localStorage = { getItem: () => null, setItem: () => {} };
global.window = {};
global.document = {
  getElementById: id => els[id] || (els[id] = { value: "", textContent: "", innerHTML: "", style: {} }),
  createElement: () => ({}),
};
eval(js + "\nglobal.__items = actions(parse(SAMPLE));");
const py = JSON.parse(fs.readFileSync(process.argv[2], "utf8")).action_items;
const pick = a => a.map(i => [i.owner, i.task, i.due]);
const ok = JSON.stringify(pick(global.__items)) === JSON.stringify(pick(py));
console.log(ok ? `demo parity OK (${py.length} items)` : "MISMATCH\n" + JSON.stringify(pick(global.__items)) + "\n" + JSON.stringify(pick(py)));
process.exit(ok ? 0 : 1);
