import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

// Same data-URL module loading convention used by the other frontend tests.
const source = readFileSync(new URL('../stream-tutorial.js', import.meta.url), 'utf8');
const {streamSummaryHtml} = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);

test('review shows selected regions separately from additional countries', () => {
  const html = streamSummaryHtml({name:'Conflict', source:'newscatcher', interval_minutes:30,
    params:{coverage_regions:['europe','asia'], coverage_countries:['US'],
      event_presets:['armed_conflict'], event_vocabulary_version:'optimized-v1'}},
    {coverage_regions:{europe:'Europe',asia:'Asia'},countries:{US:'United States'}});
  assert.match(html, /Regional focus/);
  assert.match(html, /Europe, Asia/);
  assert.match(html, /United States/);
  assert.match(html, /optimized-v1/);
});
