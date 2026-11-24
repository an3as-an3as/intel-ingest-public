import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {modelEfforts} from '../models.js';

test('effort choices are provider-specific, not universal reasoning assumptions',()=>{
 assert.deepEqual(modelEfforts('anthropic',{efforts:['low','high']}),['auto','low','high']);
 for(const provider of ['openai','deepseek','gemini','ollama'])assert.deepEqual(modelEfforts(provider,{efforts:['high']}),['auto']);
});

test('model UI has independent providers, explicit discovery and no browser credential fields',()=>{
 const source=readFileSync(new URL('../models.js',import.meta.url),'utf8');
 assert.match(source,/classify/);assert.match(source,/summary/);
 assert.match(source,/provider=\$\{encodeURIComponent\(provider\)\}/);
 assert.match(source,/Discovery requires an explicit refresh/);
 assert.ok(!/localStorage|sessionStorage|name=".*api_key/.test(source));
 assert.match(source,/No inference was run/);
});
