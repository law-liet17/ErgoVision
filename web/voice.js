/* Voice input for the task-detail forms.

   A supervisor says the task — "Twelve kg box, lifts it about twenty times a minute,
   grip is poor, holds it for more than a minute" — and the form is filled:
   load 12 kg, 20 per minute, poor grip, held over a minute.

   Listening uses the browser's own speech-to-text (Web Speech API), so nothing goes to
   a paid service. The text only ever FILLS a form: the caller shows the filled form and
   scores it after the user has confirmed or corrected it. English for now.

     parseTaskSpeech(text) -> { facts: {load_kg, per_min, coupling, static_hold, hours}, heard: {...} }
     fillFor(facts, fields) -> { fieldKey: value } for the fields this form actually has
*/

const UNITS = {
  zero: 0, one: 1, two: 2, three: 3, four: 4, five: 5, six: 6, seven: 7, eight: 8, nine: 9,
  ten: 10, eleven: 11, twelve: 12, thirteen: 13, fourteen: 14, fifteen: 15, sixteen: 16,
  seventeen: 17, eighteen: 18, nineteen: 19,
};
const TENS = { twenty: 20, thirty: 30, forty: 40, fifty: 50, sixty: 60, seventy: 70, eighty: 80, ninety: 90 };

/* "twelve kg, twenty five times" -> "12 kg 25 times"; "two and a half" -> "2.5"; "one hundred and twenty" -> "120" */
export function wordsToNumbers(text) {
  const tokens = String(text).toLowerCase()
    .replace(/(\d)([a-z])/g, '$1 $2')            // "12kg" -> "12 kg"
    .replace(/[-–]/g, ' ').replace(/[^a-z0-9./\s]/g, ' ')
    .split(/\s+/).filter(Boolean);
  const out = [];
  let num = null;
  const flush = () => { if (num !== null) { out.push(String(num)); num = null; } };
  const roundHundreds = () => num !== null && num >= 100 && num % 100 === 0;
  for (let i = 0; i < tokens.length; i++) {
    const t = tokens[i], next = tokens[i + 1];
    if (/^\d+(\.\d+)?$/.test(t)) { flush(); num = parseFloat(t); continue; }
    if (t === 'hundred' && num !== null) { num *= 100; continue; }
    if (t === 'and' && num !== null && next === 'a' && tokens[i + 2] === 'half') { num += 0.5; i += 2; continue; }
    if (t === 'and' && roundHundreds() && (next in UNITS || next in TENS)) continue;
    if (t === 'point' && num !== null && next in UNITS) { num = parseFloat(num + '.' + UNITS[next]); i++; continue; }
    if (t in TENS) { if (roundHundreds()) num += TENS[t]; else { flush(); num = TENS[t]; } continue; }
    if (t in UNITS) {
      const tensSoFar = num !== null && num >= 20 && num % 10 === 0 && num % 100 !== 0;
      if (tensSoFar || roundHundreds()) num += UNITS[t]; else { flush(); num = UNITS[t]; }
      continue;
    }
    flush();
    out.push(t);
  }
  flush();
  return out.join(' ');
}

const N = '(\\d+(?:\\.\\d+)?)';
const GRIP = { good: 'good', fair: 'fair', ok: 'fair', okay: 'fair', reasonable: 'fair', average: 'fair',
               poor: 'poor', bad: 'poor', unacceptable: 'unacceptable' };
const GRIP_WORD = '(good|fair|ok|okay|reasonable|average|poor|bad|unacceptable)';
const GRIP_NOUN = '(?:grip|grips|handle|handles|coupling|hand hold|handhold)';

/* Pull the numbers and keywords a task-detail form needs out of what was said. */
export function parseTaskSpeech(text) {
  const s = ' ' + wordsToNumbers(text) + ' ';
  const facts = {}, heard = {};
  const take = (key, value, match) => { facts[key] = value; heard[key] = match.trim(); };
  let m;

  // load: "12 kg", "12 kilos"
  if ((m = s.match(new RegExp(N + ' (?:kg|kgs|kilo|kilos|kilogram|kilograms)\\b')))) take('load_kg', +m[1], m[0]);

  // frequency: "20 times a minute", "20 lifts per minute", "20/min", "120 times an hour", "every 30 seconds"
  if ((m = s.match(new RegExp(N + ' (?:(?!kg\\b)[a-z]+ ){0,2}(?:a|an|per|each|every|/) ?(minute|min|hour|hr)s?\\b')))) {
    take('per_min', /^h/.test(m[2]) ? +(m[1] / 60).toFixed(2) : +m[1], m[0]);
  } else if ((m = s.match(new RegExp(N + ' ?/ ?min\\b')))) {
    take('per_min', +m[1], m[0]);
  } else if ((m = s.match(new RegExp('every ' + N + ' seconds?\\b')))) {
    take('per_min', +(60 / m[1]).toFixed(2), m[0]);
  }

  // grip: "grip is poor", "poor grip", "no handles"
  if ((m = s.match(new RegExp(GRIP_NOUN + ' (?:is |are |was |looks )?(?:very |quite |really )?' + GRIP_WORD + '\\b')))
      || (m = s.match(new RegExp('\\b' + GRIP_WORD + ' ' + GRIP_NOUN)))) {
    take('coupling', GRIP[m[1]], m[0]);
  } else if ((m = s.match(/\bno (?:handles?|hand ?holds?|grip)\b/))) {
    take('coupling', 'poor', m[0]);
  }

  // held: "holds it for more than a minute", "held over 2 minutes", "static posture"
  const HOLD = '\\b(?:hold|holds|held|holding|keeps?|kept|stays?|static)\\b';
  if ((m = s.match(/\b(?:not|never|doesn t|does not|don t|do not)(?: (?:be|being|it|really))? (?:hold|holds|held|holding|static)\b/))) {
    take('static_hold', false, m[0]);
  } else if ((m = s.match(new RegExp(HOLD + '[a-z0-9 ]{0,40}?\\b(?:more than|over|longer than|at least|above) (?:a|one|1) minute')))
      || (m = s.match(/\bstatic (?:posture|hold|load)\b/))) {
    take('static_hold', true, m[0]);
  } else if ((m = s.match(new RegExp(HOLD + '[a-z0-9 ]{0,40}?' + N + ' minutes')))) {
    take('static_hold', +m[1] >= 1, m[0]);
  }

  // time on task: "6 hours a day", "for 8 hours per shift"
  if ((m = s.match(new RegExp(N + ' (?:hours?|hrs?)\\b(?: (?:a|per|each|every|in the|in a) (?:day|shift))?')))
      && !new RegExp(N + ' (?:times )?(?:an|per|a) hour').test(m[0])) {
    take('hours', +m[1], m[0]);
  }
  return { facts, heard };
}

/* Upper bound in hours of a duration option: "1h" -> 1, "2to4h" -> 4, "lt2h" -> 2, "gt8h" -> Infinity. */
function hoursBound(value) {
  const v = String(value);
  if (v.startsWith('gt')) return Infinity;
  const m = v.match(/(\d+(?:\.\d+)?)h$/);
  return m ? +m[1] : NaN;
}

function optionFor(field, wanted) {
  const values = field.options.map(o => String(o[0]));
  const alias = { fair: ['fair', 'reasonable'], unacceptable: ['unacceptable', 'poor'], good: ['good'], poor: ['poor'] };
  return (alias[wanted] || [wanted]).find(v => values.includes(v));
}

/* Map the facts onto whichever of these fields a form has ({key, type, options}). */
export function fillFor(facts, fields) {
  const byKey = Object.fromEntries(fields.map(f => [f.key, f]));
  const out = {};
  const put = (key, value) => { if (byKey[key] && value !== undefined) out[key] = value; };

  put('load_kg', facts.load_kg);
  if (facts.per_min !== undefined) {
    put('lifts_per_min', facts.per_min);
    put('efforts_per_min', facts.per_min);
    put('repeated_actions', facts.per_min > 4);   // RULA/REBA: repeated more than 4 times a minute
  }
  if (facts.coupling) {
    if (byKey.coupling) put('coupling', optionFor(byKey.coupling, facts.coupling));
    if (byKey.grip && byKey.grip.type === 'select') put('grip', optionFor(byKey.grip, facts.coupling));
  }
  if (facts.static_hold !== undefined) put('static_posture', facts.static_hold);
  if (facts.load_kg && (facts.static_hold || facts.per_min > 4)) put('load_static_or_repeated', true);
  if (facts.hours !== undefined) {
    put('hours_per_day', facts.hours);
    if (byKey.duration && byKey.duration.type === 'select') {
      const opt = byKey.duration.options.find(o => facts.hours <= hoursBound(o[0]));
      if (opt) put('duration', opt[0]);
    }
  }
  return out;
}

export function speechSupported() {
  return typeof window !== 'undefined' && !!(window.SpeechRecognition || window.webkitSpeechRecognition);
}

/* Listen once; onText(text, isFinal) gets the transcript as it grows. Returns the recogniser (call .stop()). */
export function listen({ onText, onEnd, onError, lang = 'en-IN' }) {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  const rec = new SR();
  rec.lang = lang;
  rec.interimResults = true;
  rec.continuous = false;
  rec.onresult = ev => {
    let text = '';
    for (const r of ev.results) text += r[0].transcript;
    onText(text, ev.results[ev.results.length - 1].isFinal);
  };
  rec.onerror = ev => onError && onError(ev.error);
  rec.onend = () => onEnd && onEnd();
  rec.start();
  return rec;
}
