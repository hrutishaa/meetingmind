// Runs the browser demo's logic on the sample and checks it matches the Python package:
// action items for samples/weekly_sync.txt, and the team dashboard for the bundled sample team.
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
eval(js + "\nglobal.__items = actions(parse(SAMPLE));\nglobal.__dash = (t) => dashboard(TEAM.as_of, t, TEAM.meetings);\nglobal.__TEAM = TEAM;");
const py = JSON.parse(fs.readFileSync(process.argv[2], "utf8")).action_items;
const pick = a => a.map(i => [i.owner, i.task, i.due]);
const ok = JSON.stringify(pick(global.__items)) === JSON.stringify(pick(py));
console.log(ok ? `demo parity OK (${py.length} items)` : "MISMATCH\n" + JSON.stringify(pick(global.__items)) + "\n" + JSON.stringify(pick(py)));

// Dashboard: the demo's JS KPIs vs. `meetingmind dashboard --sample --json` (SQL over SQLite).
const { execFileSync } = require("child_process");
const python = process.env.PYTHON || "python";
let dashOk = true;
for (const team of [null, ...new Set(global.__TEAM.meetings.map(m => m.team))]) {
  const args = ["-m", "meetingmind", "dashboard", "--sample", "--json", ...(team ? ["--team", team] : [])];
  const want = JSON.parse(execFileSync(python, args, { cwd: __dirname + "/..", encoding: "utf8" }));
  const got = global.__dash(team);
  const same = JSON.stringify(got) === JSON.stringify(want);
  console.log(same ? `dashboard parity OK (${team || "all teams"}: ${want.summary.action_items} items, ${want.summary.overdue} overdue)`
                   : `DASHBOARD MISMATCH (${team || "all teams"})\n${JSON.stringify(got)}\n${JSON.stringify(want)}`);
  dashOk = dashOk && same;
}
process.exit(ok && dashOk ? 0 : 1);
