import { fmtP, fmtInt, nice, ordinal, showToken } from '../lib/format';
import { leanText, leanWord, tone, type Word } from '../lib/words';
import type { Result } from '../types';

function chance(p: number) {
  if (p >= 0.95) return 'a near-certain pick';
  if (p >= 0.2) return `about a ${Math.round(p * 100)}% chance`;
  return `about a 1-in-${fmtInt(nice(1 / p))} chance`;
}

export function rankPhrase(rank: number) {
  if (rank === 1) return 'The model’s #1 guess';
  if (rank <= 5) return `The model’s #${rank} guess`;
  return `Ranked ${ordinal(rank)}, outside the model’s top five`;
}

/** What the inspector says about one word, in plain words first and numbers second. */
export function WordDetails({ word, result, smooth }: { word: Word; result: Result; smooth: boolean }) {
  const v = smooth ? word.smooth : word.signal;
  const t = tone(v);
  const pieces = word.tokens.map(i => result.tokens[i]);
  const sentence = result.sentences[word.sentence];
  const head = (
    <div className="wd-head">
      <span className="wd-word">{word.text}</span>
      <span className="wd-lean" data-tone={t}>
        <span className="swatch" data-heat={`${t}${t === 'nu' ? 0 : 3}`} aria-hidden="true" />
        {leanWord(v) === 'no lean' ? 'No lean' : leanWord(v).replace(/^./, c => c.toUpperCase())}
      </span>
    </div>
  );
  if (word.rank == null || word.surprise == null || word.expected == null) {
    return (
      <>
        {head}
        <p className="wd-rank">Not scored</p>
        <p className="wd-odds">
          The very first word has nothing before it for the models to predict from, so it doesn&rsquo;t count toward the
          score. Its shading comes from the words that follow.
        </p>
      </>
    );
  }
  const p = Math.exp(-word.surprise);
  const pe = Math.exp(-word.expected);
  const leadIsFirst = word.lead === word.tokens[0];
  const verdict =
    t === 'ai'
      ? 'More predictable than the model expected here, which is AI-like.'
      : t === 'hu'
        ? 'More surprising than the model expected here, which is human-like.'
        : 'About as predictable as expected here, so no lean either way.';

  return (
    <>
      {head}
      <p className="wd-rank">{rankPhrase(word.rank)}</p>
      <p className="wd-odds">
        The model gave {pieces.length > 1 ? 'this word' : 'it'} {chance(p)}. A typical word here gets {chance(pe)}.
      </p>
      <p className="wd-verdict">{verdict}</p>
      <table className="wd-top">
        <caption>
          The model&rsquo;s top five guesses{pieces.length > 1 ? (leadIsFirst ? ' for the first piece' : ' for the first scored piece') : ''}
        </caption>
        <tbody>
          {word.top.map((g, i) => {
            const mine = i + 1 === word.rank;
            return (
              <tr key={i} data-mine={mine || undefined}>
                <th scope="row" className="wd-rankcell">
                  #{i + 1}
                </th>
                <td className="wd-guess">
                  {showToken(g.text)}
                  {mine && <span className="wd-mine">written</span>}
                </td>
                <td className="wd-bar" aria-hidden="true">
                  <span style={{ width: `${Math.max(2, g.p * 100)}%` }} />
                </td>
                <td className="wd-p">{fmtP(g.p)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="wd-meta">
        Surprise {word.surprise.toFixed(2)} vs {word.expected.toFixed(2)} expected
        {pieces.length > 1 && (
          <>
            {' '}
            &middot; read as {pieces.length} pieces: {pieces.map(x => showToken(x.text)).join(' + ')}
          </>
        )}
      </p>
      {sentence && (
        <p className="wd-sentence">
          This sentence: {leanText(sentence.lean).toLowerCase()} ({sentence.score.toFixed(3)}). A hint, not a verdict.
        </p>
      )}
    </>
  );
}
