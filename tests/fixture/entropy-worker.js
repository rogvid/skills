// Loaded by ?entropy=1 (issue #10). A Worker has its own global scope, which
// page init scripts never run in — so what this posts back is a clock the
// recorder can only have frozen by re-injecting the freeze into the worker
// itself. Its answer is rendered into the page, which puts it in the stills.
self.postMessage(Date.now());
