// Development-only fixture texts for the mock API. Synthetic samples written for testing the UI;
// none of this is shipped in the production build.

export type Style = 'ai' | 'human';

/** One paragraph of a fixture: its writing style and the Binoculars score it should land near. */
export type FixtureParagraph = { style: Style; target: number; text: string };

export type Fixture = { id: string; title: string; paragraphs: FixtureParagraph[] };

const ai = (target: number, text: string): FixtureParagraph => ({ style: 'ai', target, text });
const human = (target: number, text: string): FixtureParagraph => ({ style: 'human', target, text });

export const fixtures: Fixture[] = [
  {
    id: 'ai-essay',
    title: 'Essay: public libraries (AI-style)',
    paragraphs: [
      ai(0.78, "In today's rapidly evolving digital landscape, public libraries continue to play a vital role in fostering community, learning, and equal access to information. While some argue that the internet has made libraries obsolete, a closer look reveals that their value has not diminished but rather transformed."),
      ai(0.8, 'First and foremost, libraries serve as essential hubs for digital inclusion. Not every household has reliable internet access or a modern computer, and libraries help bridge this gap by providing free Wi-Fi, public computers, and technology training. For job seekers, students, and older adults, these resources can be transformative, opening doors to opportunities that might otherwise remain out of reach.'),
      ai(0.79, 'Furthermore, libraries offer a unique sense of community that online platforms struggle to replicate. From story time for young children to book clubs and language exchange programs, libraries create welcoming spaces where people from diverse backgrounds can connect, collaborate, and learn from one another. In an era marked by increasing social isolation, these shared spaces are more important than ever.'),
      ai(0.81, 'Additionally, libraries play a crucial role in promoting information literacy. With misinformation spreading rapidly online, librarians are uniquely positioned to help patrons evaluate sources, think critically, and navigate the complex information ecosystem. This guidance empowers individuals to make informed decisions and participate meaningfully in civic life.'),
      ai(0.84, 'Of course, libraries must continue to adapt in order to remain relevant. Investing in digital collections, flexible study spaces, and innovative programming will ensure that they meet the evolving needs of their communities. Partnerships with schools, local businesses, and nonprofit organizations can further expand their reach and impact.'),
      ai(0.77, 'In conclusion, public libraries are far from obsolete. By embracing change while staying true to their core mission of providing free and open access to knowledge, libraries will remain indispensable pillars of their communities for generations to come. Supporting them is not merely an act of nostalgia, but a meaningful investment in a more informed, connected, and equitable society.'),
    ],
  },
  {
    id: 'human-essay',
    title: "Essay: grandfather's hardware store (human)",
    paragraphs: [
      human(1.03, 'My grandfather ran a hardware store in Elmira for thirty-one years, and the thing I remember most is the smell: cut keys, fertilizer, and the burnt-coffee smell of the pot he never once washed. I worked there the summer I turned fifteen. He paid me four dollars an hour in cash and a Snickers bar, which he called my "benefits package."'),
      human(1.0, 'Most of the job was boring. I sorted bins of screws that customers had mixed up, swept, and learned that nobody ever buys just one hinge. But some days were weird in a good way. A woman came in once asking for a "thingamajig for the doohickey on a toilet," and my grandfather walked her straight to aisle six and handed her a flapper valve without saying a word. She looked at him like he was a wizard.'),
      human(1.05, "He wasn't great with computers. The register was older than my mom, and when the credit card machine froze he'd unplug it, count to ten out loud, and plug it back in like he was performing CPR. It worked maybe half the time. The other half he'd write the number on a yellow legal pad and \"deal with it Monday,\" which I'm pretty sure was illegal."),
      human(0.97, "What I didn't get until later was that the store wasn't really about selling stuff. Mr. Okafor came in every Thursday to buy one bag of birdseed and talk about the Bills for forty minutes. The kids from the Catholic school bought penny nails to build things their teachers definitely hadn't assigned. My grandfather knew everybody's furnace, everybody's dog, and which of them was going through a divorce."),
      human(1.04, "The store closed in 2019. There's a vape shop there now, and I can't walk past it without counting to ten under my breath. I don't think I'll ever be able to fix a toilet as well as he could, but I know exactly which aisle the flapper valves were in."),
    ],
  },
  {
    id: 'mixed',
    title: 'Blog post: sourdough (human with an AI-written middle)',
    paragraphs: [
      human(1.02, 'I started baking bread during the first winter I lived alone, mostly because my apartment was freezing and the oven was the only thing that worked. My first loaf came out the size and density of a hockey puck. I ate it anyway, with a lot of butter, standing over the sink.'),
      ai(0.78, 'Sourdough baking is a rewarding practice that combines science, patience, and creativity. At its core, sourdough relies on a natural starter, a living culture of wild yeast and lactic acid bacteria that ferments the dough and gives the bread its distinctive tangy flavor. Maintaining a healthy starter requires regular feeding with flour and water, as well as attention to temperature and timing.'),
      ai(0.77, 'One of the key benefits of sourdough is its improved digestibility. The long fermentation process helps break down gluten and phytic acid, making nutrients more accessible and the bread easier on the stomach for many people. Additionally, sourdough has a lower glycemic index than conventional bread, which can contribute to more stable blood sugar levels. These qualities, combined with its complex flavor and satisfying texture, have made sourdough increasingly popular among home bakers.'),
      ai(0.8, 'To achieve consistent results, it is important to understand the role of hydration, shaping, and proofing. Higher hydration doughs produce a more open crumb but can be challenging to handle. Proper shaping builds surface tension, which helps the loaf rise and develop an attractive ear during baking. Finally, a well-timed proof ensures that the dough has fermented enough to rise without collapsing in the oven.'),
      human(1.04, 'Anyway. My starter is named Gary, after a coworker who also smelled faintly of vinegar and refused to die. Gary has survived two moves, a week in a hot car, and one incident where my roommate thought he was pancake batter. The bread is better now. Not good, exactly, but better: the crumb has holes, the crust crackles when it cools, and last month my neighbor asked for a slice instead of politely declining one.'),
    ],
  },
  {
    id: 'short',
    title: 'Short email reply (about 30 words)',
    paragraphs: [
      ai(0.76, 'Thank you for reaching out regarding the project timeline. I have reviewed the details and believe we can deliver the final report by Friday, ensuring all requirements are met.'),
    ],
  },
];

export const fixtureText = (f: Fixture) => f.paragraphs.map(p => p.text).join('\n\n');

/** Words that make unknown text lean AI-like in the mock, so typed text still gives varied results. */
export const aiCueWords = [
  'furthermore', 'additionally', 'moreover', 'crucial', 'vital', 'landscape', 'delve', 'foster',
  'fostering', 'essential', 'empowers', 'transformative', 'in conclusion', 'ultimately', 'pivotal',
  'seamless', 'robust', 'navigate', 'tapestry', 'realm', 'meaningful', 'ensure', 'ensuring',
];
