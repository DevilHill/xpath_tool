'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const {spawnSync} = require('node:child_process');

test('Python 断点调试真实进程回归', () => {
  const python = process.env.WBOT_TEST_PYTHON || 'python';
  const result = spawnSync(python,['-I','-X','utf8',path.join(__dirname,'test_flow_debug_runner.py')],
    {encoding:'utf8',windowsHide:true,timeout:60000,maxBuffer:1024*1024});
  assert.equal(result.status,0,result.stdout + result.stderr + (result.error || ''));
});
