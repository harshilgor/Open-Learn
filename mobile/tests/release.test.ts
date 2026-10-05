import {strict as assert} from 'node:assert';
import {test} from 'node:test';
import {verifiedStoreUrl} from '../src/release';
test('only accepts official platform-specific store listings',()=>{
 assert.ok(verifiedStoreUrl('ios','https://apps.apple.com/us/app/open-learn/id123456'));
 assert.ok(verifiedStoreUrl('android','https://play.google.com/store/apps/details?id=dev.openlearn.app'));
 for(const invalid of ['http://play.google.com/store/apps/details?id=test','https://example.com/app','https://play.google.com/store/apps/details','https://secret@play.google.com/store/apps/details?id=test'])assert.equal(verifiedStoreUrl('android',invalid),null);
 assert.equal(verifiedStoreUrl('ios',undefined),null);
 assert.equal(verifiedStoreUrl('android','https://apps.apple.com/us/app/open-learn/id123456'),null);
});
