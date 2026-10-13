import {expect,it} from 'vitest';
import {isSocialTurn} from '@/lib/social-turn';
it.each(['Hi!','  hello buddy… ','Ｔｈａｎｋ　ｙｏｕ','Good morning'])('routes a whole social turn directly: %s',message=>expect(isSocialTurn(message)).toBe(true));
it.each(['Hi, open YouTube','Hello, remind me tomorrow','Thanks, now explain photosynthesis','Hi\nWhat is gravity?','hi there or hello','Good morning, quiz me'])('retains normal routing for a substantive request: %s',message=>expect(isSocialTurn(message)).toBe(false));
