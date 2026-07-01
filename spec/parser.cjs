const path = require('node:path');
const { spawn } = require('node:child_process');

const root = path.resolve(__dirname, '..');
const bridge = path.join(__dirname, 'parse.py');

// Implements rdf-test-suite's IParser interface. These RDF 1.2 manifests only
// contain syntax tests, so they inspect success/failure rather than RDFJS quads.
module.exports = {
  parse(data, baseIRI, options) {
    return new Promise((resolve, reject) => {
      const python = process.env.PYTHON || 'python';
      const pythonPath = [root, process.env.PYTHONPATH].filter(Boolean).join(path.delimiter);
      const child = spawn(python, [bridge], {
        cwd: root,
        env: { ...process.env, PYTHONPATH: pythonPath },
        stdio: ['pipe', 'ignore', 'pipe'],
      });
      let stderr = '';

      child.stderr.setEncoding('utf8');
      child.stderr.on('data', chunk => { stderr += chunk; });
      child.on('error', reject);
      child.on('close', code => {
        if (code === 0) {
          resolve([]);
        } else {
          reject(new Error(stderr.trim() || `Python RDF parser exited with status ${code}`));
        }
      });
      child.stdin.end(JSON.stringify({ data, baseIRI, format: options.format }));
    });
  },
};
