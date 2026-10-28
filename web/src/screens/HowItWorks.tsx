import { DOWNLOAD_HREF, notes } from '../copy';
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
  const clf = !!status?.classifier?.ready;
  const minWords = status?.classifier?.min_words ?? 50;
  // The public site runs the detector alone; the word marks live in Squint for Mac.
  // Inside Squint for Mac, preview means this Mac has under 16 GB of memory.
  const preview = status?.mode === 'preview';
  const app = !!status?.app;
  const mac = (
    <a className="text-link" href={DOWNLOAD_HREF}>
      Squint for Mac
    </a>
  );
  return (
    <div className="screen how page">
      <article className="galley page-sheet">
      <header className="screen-head">
        <h1>How it works</h1>
        <p className="lede">
          {preview
            ? app
              ? 'A detector trained on human and AI writing gives the verdict. On Macs with 16 GB of memory, a second method marks how predictable each word is.'
              : <>A detector trained on human and AI writing gives the verdict. A second method, in {mac}, marks how predictable each word is.</>
            : clf
              ? 'Squint uses two methods. A detector trained on human and AI writing gives the verdict. A second method measures how predictable each word is, and that is what the word marks show.'
              : 'Squint doesn’t hunt for giveaway words. It measures how predictable each word is, and compares that with how predictable it ought to be.'}
        </p>
      </header>

      {clf && (
        <section className="how-section" aria-labelledby="detector-title">
          <h2 id="detector-title" className="section-title">
            The verdict: a trained detector
          </h2>
          <div className="prose">
            <p>
              The verdict comes from a language model that was trained to tell the two apart. It learned from thousands of
              texts by people, including students writing in a second language, and from text written by ChatGPT and Claude
              on the same kinds of topics.
            </p>
            <p>
              It reads the whole text and rates how likely it is to be AI writing. Squint only says{' '}
              <em className="term">Likely AI</em> when that rating is very high, high enough that in testing it flagged 4 of
              1,340 human texts, about 1 in 330. When the rating is low it says <em className="term">Likely human</em>, and in between
              it says <em className="term">Uncertain</em>.
            </p>
            <p>
              Under {minWords} words it won&rsquo;t give a verdict. Short snippets don&rsquo;t carry enough signal, and in
              testing the detector wrongly flagged about 2.5% of short human texts.
            </p>
            {preview && (
              <p>
                From 150 words it also reads overlapping 150-word passages. The AI-written share is the share of words inside a
                flagged passage, and each flagged passage is shaded on your text with a blue bracket beside it.
              </p>
            )}
          </div>
        </section>
      )}

      <section className="how-section" aria-labelledby="method-title">
        <h2 id="method-title" className="section-title">
          {preview ? (app ? 'The word marks, on 16 GB Macs' : 'The word marks, in Squint for Mac') : clf ? 'The word marks: two models, one ratio' : 'Two models, one ratio'}
        </h2>
        <div className="prose">
          {preview && (
            <p>
              {app
                ? 'The word marks need two 7-billion-parameter models and 16 GB of memory. This Mac has less, so Squint runs the detector alone.'
                : <>The word marks need two 7-billion-parameter models, so they run on your own computer in {mac}. This site runs
              the detector alone.</>}
            </p>
          )}
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
                <b>Divide one by the other.</b> That ratio is the score.{' '}
                {clf
                  ? 'Lower means more predictable. Squint shows it for every word, but the verdict comes from the trained detector.'
                  : 'Below the cutoffs it reads as AI-like, above them as human-like. In between, Squint says Uncertain and leaves it there.'}
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
          Reading the marks
        </h2>
        <div className="prose">
          <p>
            {preview ? (app ? 'On 16 GB Macs' : 'In Squint for Mac') : 'In a result'}, every word has its own little score: was it more or less predictable than the models expected at
            that spot?
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
            escape.&rdquo; The stock phrase at the start is marked in blue with solid underlines, meaning AI-like. The words about
            the aunt and the bees are marked in orange with dotted underlines, meaning human-like.
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
              Blue, solid underline: more predictable than expected, which is AI-like.
            </dd>
          </div>
          <div className="row">
            <dt className="row-label">
              <span className="legend-sample" data-heat="hu3">
                word
              </span>
            </dt>
            <dd className="row-body">Orange, dotted underline: more surprising than expected, which is human-like.</dd>
          </div>
          <div className="row">
            <dt className="row-label">
              <span className="legend-sample" data-heat="nu0">
                word
              </span>
            </dt>
            <dd className="row-body">Unmarked: about as predictable as expected. No lean either way.</dd>
          </div>
        </dl>
        <div className="prose">
          <p>
            A wash and a heavier underline mean a stronger lean. <b>Clear leans</b> averages each word with its neighbours and
            marks only the words that lean hard, so you see stretches rather than single words. <b>Every word</b> shows each
            word&rsquo;s own score, which is much noisier: plenty of human words are predictable, and that&rsquo;s fine.
          </p>
          <p>
            Hover or tab to a word to see the model&rsquo;s top five guesses for that spot and where your word ranked. The
            sentence lean shown there is a hint for where to look, never a verdict on its own.
          </p>
          {!preview && (
            <p>
              For texts of 150 words or more, Squint also {clf ? 'runs the detector on' : 'scores'} overlapping 150-word
              passages. The AI-written share is the share of words that sit inside a flagged passage, and each flagged passage gets
              a blue bracket in the margin.
            </p>
          )}
        </div>
      </section>

      <section className="how-section" aria-labelledby="blind-title">
        <h2 id="blind-title" className="section-title">
          Blind spots
        </h2>
        <dl className="rows blind">
          <div className="row">
            <dt className="row-label">Current AI models</dt>
            <dd className="row-body">
              {clf
                ? 'The detector was trained on ChatGPT and Claude. In testing it caught 747 of 751 ChatGPT samples and 699 of 733 Claude samples, so some Claude writing gets through. Gemini and other models haven’t been tested, and new model versions may slip past it until it is retrained.'
                : 'Writing from current models scores inside the range people write in, so Squint misses most of it. In testing it caught none of 288 ChatGPT samples and 32 of 289 Claude samples. Gemini hasn’t been tested.'}{' '}
              <a className="text-link" href={hrefFor('accuracy')}>
                See the accuracy page
              </a>
            </dd>
          </div>
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
              {preview
                ? `A few sentences don’t give the detector much to read. Under 20 words Squint won’t try. Under ${minWords} it gives no verdict. Under 150 the verdict is marked low confidence, and there is no AI-written share.`
                : clf
                ? `A few sentences don’t give the models much to measure. Under 20 words Squint won’t try. Under ${minWords} it shows the word marks but no verdict. Under 150 the verdict is marked low confidence, and there is no AI-written share.`
                : 'A few sentences don’t give the models much to measure. Under 20 words Squint won’t try. Under 150 it gives a rough verdict marked low confidence, and no AI-written share.'}
            </dd>
          </div>
          {clf && (
            <div className="row">
              <dt className="row-label">College essays</dt>
              <dd className="row-body">
                Human college essays from a source the detector never trained on are wrongly flagged about 4 to 6% of the time.
                That is the largest gap still open.
              </dd>
            </div>
          )}
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
              {preview
                ? 'Forms, boilerplate, lists and heavily templated text are predictable by design and can read as machine-made. Weigh a verdict on them with care.'
                : 'Forms, boilerplate, lists and heavily templated text are predictable by design. The two-model ratio corrects for much of this, not all of it.'}
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
      </article>
    </div>
  );
}
