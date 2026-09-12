ObjC.import("AppKit");

function run(argv) {
  const apps = $.NSWorkspace.sharedWorkspace.runningApplications;
  const pids = [];
  for (let i = 0; i < apps.count; i++) {
    const app = apps.objectAtIndex(i);
    if (app.bundleURL && ObjC.unwrap(app.bundleURL.path) === argv[1]) {
      pids.push(Number(app.processIdentifier));
      if (argv[0] === "quit" && !app.terminate) {
        throw new Error("T3 refused normal termination");
      }
    }
  }
  return JSON.stringify(pids);
}
