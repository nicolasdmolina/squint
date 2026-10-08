/**
 * PDF text arrives with a hard line break at the end of every printed line. Left alone, each line
 * reads as its own paragraph (and its own sentence) to the server, so the evidence gets chopped
 * into one-line pieces. This joins wrapped lines back into paragraphs before the text reaches the
 * editor, where the writer can still review it.
 *
 * Only blocks that look like wrapped prose are touched (several lines, most of them long); short
 * lines such as lists, headings and table rows keep their breaks. A short line that ends a
 * sentence is read as the end of a paragraph. A word hyphenated across a line break is rejoined.
 * The text stays in the editor, so anything this gets wrong can be fixed by hand.
 */
export function reflowPdfText(text: string): string {
  return text
    .split(/\n{2,}/)
    .map(reflowBlock)
    .join('\n\n');
}

const ENDS_SENTENCE = /[.!?:;"'”’)\]]$/;

function reflowBlock(block: string): string {
  const lines = block.split('\n');
  if (lines.length < 3) return block;
  const lengths = lines.map(l => l.trim().length).sort((a, b) => a - b);
  const typical = lengths[Math.floor(lengths.length * 0.8)];
  const median = lengths[Math.floor(lengths.length / 2)];
  if (median < 40) return block;

  let out = lines[0].trimEnd();
  for (let i = 1; i < lines.length; i++) {
    const prev = lines[i - 1].trim();
    const next = lines[i].trim();
    if (!next) continue;
    if (prev.length < typical * 0.7 && ENDS_SENTENCE.test(prev)) out += `\n\n${next}`;
    else if (/\p{L}-$/u.test(prev) && /^\p{Ll}/u.test(next)) out = out.slice(0, -1) + next;
    else out += ` ${next}`;
  }
  return out;
}
