import { notes } from '../copy';
import { ArrowRightIcon } from '../components/Icons';
import { hrefFor } from '../lib/hooks';
import type { Status } from '../types';

type Piece = [text: string, heat?: string];

// A labelled specimen, not a real result: one stock phrase, then one particular one.
const SPECIMEN: Piece[] = [
  ['In', 'ai2'],
  [' '],
  ['today’s', 'ai3'],
  [' '],
  ['fast-paced', 'ai4'],
  [' '],
  ['world,', 'ai3'],
  [' '],
  ['it', 'ai2'],
  [' '],
  ['is', 'ai3'],
  [' '],
  ['important', 'ai4'],
  [' '],
  ['to', 'ai3'],
  [' '],
  ['note', 'ai2'],
  [' '],
  ['that', 'nu0'],
  [' '],
  ['my', 'nu0'],
  [' '],
  ['aunt', 'hu2'],
  [' '],
  ['kept', 'hu3'],
  [' '],
  ['bees', 'hu4'],
  [' '],
  ['on', 'hu1'],
  [' '],
  ['a', 'nu0'],
  [' '],
  ['fire', 'hu3'],
  [' '],
  ['escape.', 'hu2'],
];

export function HowItWorks({ status }: { status: Status | null }) {
  const pair = status?.model_pair;
  return (
    <div className="screen how">
      <header className="screen-head">
        <h1>How it works</h1>
        <p className="lede">
          Squint doesn&rsquo;t hunt for giveaway words. It measures how predictable each word is, and compares that with how
          predictable it ought to be.
        </p>
      </header>

      <section className="how-section" aria-labelledby="method-title">
        <h2 id="method-title" className="section-title">
          Two models, one ratio
        </h2>
        <div className="prose">
          <p>
            A language model is a prediction machine. Give it the words so far and it guesses the next one. AI writing is made
            by picking likely next words, so it tends to be predictable. People surprise the models more.
          </p>
          <p>
            Some writing is predictable no matter who wrote it, though. A recipe, a legal clause or a list of instructions would
            fool a detector that only measured predictability. So Squint uses a method called Binoculars, which brings in a
            second, closely related model.
          </p>
          <ol className="steps">
            <li>
              <div>
                <b>How surprising was each word?</b> One model reads your text and measures how surprised it is by every word you
                actually wrote.
              </div>
            </li>
            <li>
              <div>
                <b>How surprising should it be?</b> The two models compare their own guesses at each spot. That sets the
                surprise you&rsquo;d expect from writing on this topic, in this style.
              </div>
            </li>
            <li>
              <div>
                <b>Divide one by the other.</b> That ratio is the score. Below the cutoffs it reads as AI-like, above them as
                human-like. In between, Squint says Uncertain and leaves it there.
              </div>
            </li>
          </ol>
          <p>
            The cutoffs come from testing Squint on writing whose source was known. The{' '}
            <a className="text-link" href={hrefFor('accuracy')}>
              accuracy page
            </a>{' '}
            shows how that went.
          </p>
          {pair && (
            <p className="quiet">
              Models in use: {pair.observer} and {pair.performer}, both running on this machine.
            </p>
          )}
        </div>
      </section>

      <section className="how-section" aria-labelledby="heat-title">
        <h2 id="heat-title" className="section-title">
          Reading the colours
        </h2>
        <div className="prose">
          <p>
            In &ldquo;Show me why&rdquo;, every word is shaded by its own little score: was it more or less predictable than
            the models expected at that spot?
          </p>
        </div>
        <figure className="specimen-figure">
          <div className="specimen-frame">
            <p className="specimen" aria-hidden="true">
              {SPECIMEN.map(([t, h], i) =>
                h ? (
                  <span key={i} className="w" data-heat={h}>
                    {t}
                  </span>
                ) : (
                  t
                ),
              )}
            </p>
            <div className="specimen-notes" aria-hidden="true">
              <span className="specimen-note is-ai">A stock phrase: predictable, AI-like</span>
              <span className="specimen-note is-hu">A particular memory: surprising, human-like</span>
            </div>
          </div>
          <figcaption className="sr-only">
            Example sentence: &ldquo;In today&rsquo;s fast-paced world, it is important to note that my aunt kept bees on a fire
            escape.&rdquo; The stock phrase at the start is shaded blue with solid underlines, meaning AI-like. The words about
            the aunt and the bees are shaded amber with dotted underlines, meaning human-like.
          </figcaption>
        </figure>
        <dl className="rows key-rows">
          <div className="row">
            <dt className="row-label">
              <span className="legend-sample" data-heat="ai3">
                word
              </span>
            </dt>
            <dd className="row-body">
              Blue with a solid underline: more predictable than expected, which is AI-like.
            </dd>
          </div>
          <div className="row">
            <dt className="row-label">
              <span className="legend-sample" data-heat="hu3">
                word
              </span>
            </dt>
            <dd className="row-body">Amber with a dotted underline: more surprising than expected, which is human-like.</dd>
          </div>
          <div className="row">
            <dt className="row-label">
              <span className="legend-sample" data-heat="nu0">
                word
              </span>
            </dt>
            <dd className="row-body">Unshaded: about as predictable as expected. No lean either way.</dd>
          </div>
        </dl>
        <div className="prose">
          <p>
            Deeper shading and a heavier underline mean a stronger lean. <b>Smoothed</b> view averages each word with its
            neighbours, so you see stretches rather than single words. <b>Word by word</b> shows each word&rsquo;s own score,
            which is much noisier: plenty of human words are predictable, and that&rsquo;s fine.
          </p>
          <p>
            Hover or tab to a word to see the model&rsquo;s top five guesses for that spot and where your word ranked. Sentence
            and paragraph leans are hints for where to look, never verdicts on their own.
          </p>
          <p>
            For texts of 150 words or more, Squint also scores overlapping 150-word passages. The AI-written share is the share
            of words that sit inside a flagged passage.
          </p>
        </div>
      </section>

      <section className="how-section" aria-labelledby="blind-title">
        <h2 id="blind-title" className="section-title">
          Blind spots
        </h2>
        <p className="acc-lede">Squint is one clue, not a verdict. It is weakest in these places.</p>
        <dl className="rows blind">
          <div className="row">
            <dt className="row-label">Edited or paraphrased AI text</dt>
            <dd className="row-body">
              Rewrite AI text by hand, or run it through a paraphrasing tool, and it gets less predictable. Squint will often
              miss it, and a mix of human and AI writing can land in Uncertain.
            </dd>
          </div>
          <div className="row">
            <dt className="row-label">Short text</dt>
            <dd className="row-body">
              A few sentences don&rsquo;t give the models much to measure. Under 20 words Squint won&rsquo;t try. Under 150 it
              gives a rough verdict marked low confidence, and no AI-written share.
            </dd>
          </div>
          <div className="row">
            <dt className="row-label">Non-native English writers</dt>
            <dd className="row-body">
              Writing in a second language often means choosing safer, more common words, which can look predictable. Squint
              is tested on non-native writers so they aren&rsquo;t flagged more often than anyone else, but treat any single
              reading with care.
            </dd>
          </div>
          <div className="row">
            <dt className="row-label">Formulaic writing</dt>
            <dd className="row-body">
              Forms, boilerplate, lists and heavily templated text are predictable by design. The two-model ratio corrects for
              much of this, not all of it.
            </dd>
          </div>
        </dl>
      </section>

      <section className="how-section" aria-labelledby="privacy-title">
        <h2 id="privacy-title" className="section-title">
          Privacy
        </h2>
        <div className="prose">
          <p>{notes.privacy}</p>
          <p>
            Your text goes to the models on this machine and nowhere else. Uploaded files are read for their text and not
            kept. There are no accounts and no history: when a result is gone, it&rsquo;s gone.
          </p>
        </div>
        <a className="text-link" href={hrefFor('check')}>
          Check some writing
          <ArrowRightIcon size={16} />
        </a>
      </section>
    </div>
  );
}
