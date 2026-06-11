# Usage policy

metalworks is for authentic, transparent Reddit engagement by a single person or
a transparent team. It is not for vote manipulation, brigading, or astroturfing.
Use it that way and the tools work with you. Use it the other way and you are
violating Reddit's rules, this policy, and the trust the library is built on.

This policy covers the Reddit engagement side (`metalworks.reddit`, the
discovery loop, posting, and the MCP/plugin surfaces that drive them). The
research side reads public archives and does not post.

## What is allowed

- Reading public Reddit data for research (demand reports, subreddit intel,
  search).
- Participating in threads as yourself, or as a clearly identified member of
  your team, when you have something genuine to add.
- Disclosing your affiliation when you mention a product, brand, or project you
  are connected to.
- Drafting replies and posts with assistance, as long as the account, the voice,
  and the experience behind them are real.

## What is prohibited

- **Coordinated inauthentic behavior.** No networks of accounts acting in
  concert, no sockpuppets, no manufactured consensus.
- **Fake personas and invented account backstories.** Do not fabricate a
  history, identity, or lived experience for an account. The backstory-generation
  such tooling was deliberately **not**
  open-sourced for exactly this reason. The remaining persona field in the
  discovery loop is named `background` and is meant to carry a real account's
  real context, never a fabricated one.
- **Vote manipulation, brigading, and astroturfing.** No buying, trading,
  organizing, or automating votes. No directing groups to pile onto a thread.
- **Undisclosed promotion.** Do not promote something you are affiliated with
  while hiding that affiliation.

## Obligations when you participate

- **Disclose affiliation.** If you have a stake in what you are recommending, say
  so in the comment.
- **Respect subreddit rules.** Read them. Many subreddits ban self-promotion
  outright. metalworks can fetch a subreddit's rules for you; it cannot consent
  to them on your behalf.
- **Respect Reddit's terms.** Follow Reddit's User Agreement, the Reddit API
  terms, and the Reddit Data API terms. Respect the data-source terms for the
  archives the research side reads.

## Safeguards in the library (not a license)

- **Rate limiting is enforced in-library.** Every Reddit call goes through a
  shared rate limiter that honors `429` / `Retry-After`. Do not route around it.
- **The compliance gate is deterministic and offline.** `heuristic_check` and
  `heuristic_check_post` flag AI-tells, em-dash homoglyphs, over-promotional
  text, and length problems before anything is posted. The posting paths run it.
- **These are safeguards, not a bypass.** A passing compliance check means the
  text does not trip the heuristics. It does not mean the engagement is honest,
  disclosed, or welcome in that subreddit. That judgment is yours, and this
  policy is the standard you are held to.

If you cannot use metalworks within this policy, do not use the Reddit side of
it.
