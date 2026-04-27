# Election Rules

> **One congregation's interpretation.** This app encodes the FRCA "Rules for the Election of Office Bearers" as interpreted and applied by the maintaining congregation. It is not authoritative for any other congregation. Rules vocabulary, derivations, and edge-case readings vary, and a forking congregation MUST verify every section below against its own Election Rules before running an election with this software.
>
> The Election Rules are a *separate document* from the Church Order. Article 1 of these rules cites Article 3 of the Church Order as the source authority; the Articles 1–13 referenced throughout this document are Election Rules articles, not Church Order articles.

This document follows a three-section pattern per article:

1. **Rule text** — verbatim from the Election Rules.
2. **App's interpretation** — how the rule is encoded (or "outside scope" if procedural).
3. **Decision provenance** — for non-obvious calls, where the call came from.

Implementation lives in [`voting-app/election_rules.py`](../election_rules.py) for rule arithmetic. Other rule logic (form validation, persistence) is in [`voting-app/app.py`](../app.py); search the function name against this file to locate the implementation.

---

## Council preparation guidelines

These guidelines describe how church council selects the slate of candidates *before* using this app. The app starts at Article 4 (attendance register). The candidate-selection process is documented here for completeness only.

> Church Council shall request the congregation to nominate brothers whom they deem suitable for the office on the two Sundays prior to that meeting. Nominations from within the congregation must be signed and include reasons for suitability.
>
> A list of candidates for the election of office bearers shall be prepared during the September church council meeting. Article 2 of the Rules for the Election of Office Bearers states that the final list of candidates shall be equal to twice the number of the vacancies to be filled. Article 13 of the Rules for the Election of Office Bearers does permit church council to deviate from this article if it so desires. See also Article 3 of the Church Order.
>
> The Secretary shall ensure that there is an updated ward list available prior to the meeting. He will also supply the meeting with a list of male communicant members, including the year that previous office bearers last served in office.
>
> The Secretary shall read any valid letters of nomination that have been received from within the congregation.
>
> A list of potential candidates for both the office of elder and the office of deacon shall be compiled, starting with all the names nominated by the congregation.
>
> Each office bearer will be asked in turn by the Chairman to put forth their nomination(s) for the office of elder and/or deacon. These shall all be added to the list of potential candidates.
>
> When nominating brothers as candidates, the office bearers are not required to provide a written nomination but are expected to have given serious prior consideration to the suitability of their nomination in light of scripture (1 Timothy 3, Titus 1).
>
> Once a complete list of potential candidates has been compiled, the chairman will ask the elders of each ward to consider the names of the potential candidates from within their respective wards. The ward elders can ask for a name of a brother from within their own ward to be removed from the list of potential candidates when they are both in agreement and for a substantial reason. A substantial reason may include a lack of suitability for the office to which they have been nominated or may relate to circumstances where it is deemed wiser not to include the brother as a candidate at this time. In the interest of confidentiality, the elders do not need to state the reason to the meeting.
>
> The Chairman shall ask all the brothers present if there are any other brothers on the list that they feel require further discussion before voting. Further names can be removed from the list if the meeting is in agreement, otherwise the name will be left on the list.
>
> The Chairman shall now present the final list of names of potential candidates to the meeting. If there are more names than required (i.e. more than twice the number of vacancies) then he shall put this to a vote. The meeting may use its discretion as to whether to vote for the office of elder or deacon first. Voting shall be completed by secret ballot and the successful candidates must receive more than half the number of valid votes cast divided by the number of vacancies. If more than one round of voting is necessary, then candidates who did not receive any votes in the previous round of voting may be removed from the list.
>
> The final list of candidates shall be presented to the congregation on the following Sunday.
>
> The ward elders will ensure that they notify the brothers that have been nominated as candidates prior to the names being presented to the congregation.

**App's interpretation:** outside the scope of this software. The app expects a finalised slate to be entered via the admin "Setup" page.

---

## Article 1

**Rule text:**

> Elders and Deacons shall be elected in accordance with Article 3 of the Church Order by the church council, with the cooperation of the congregation.

**App's interpretation:** procedural framing. The app is the "cooperation" tool used during the congregational vote; it does not encode any rule logic for this article.

---

## Article 2

**Rule text:**

> On the 2 Sundays before the September church council meeting, the congregation shall be encouraged to nominate brothers whom they consider suitable for the office of elder and/or deacon. These nominations must be accompanied by reasons for suitability and must be signed by the nominator.
>
> At the September church council meeting a list of candidates shall be drawn up. The list is to have twice the number of the vacancies to be filled, so that the male communicant members may elect one half of that number.
>
> The congregation will be informed of the names of the candidates by an announcement from the pulpit on the Sunday following that church council meeting.

**App's interpretation:** when an admin enters candidates for an office, the app warns if the slate size is not exactly `2 × vacancies`. The warning is informational: a chairman with a substantive reason can override via `confirm_slate_override` per Article 13. Test coverage: `TestArticle2SlateValidation` in [`tests/test_rules_compliance.py`](../tests/test_rules_compliance.py).

---

## Article 3

**Rule text:**

> On the first Sunday after the October holidays the church council shall call the congregation together so that under its guidance and after calling upon the Name of the Lord the election may take place.

**App's interpretation:** outside scope. The chairman picks the election date when creating the election.

---

## Article 4

**Rule text:**

> At this meeting all male communicant members present must sign the attendance register.

**App's interpretation:** the app generates an `attendance_register.pdf` from the member list (admin → Codes page → Printer Pack ZIP). The chairman or task team prints it for sign-in at the door. The chairman then enters the in-person count on the manage page; this number drives Article 6b's threshold (see Article 6b below).

---

## Article 5

**Rule text:**

> Before the election takes place, the secretary shall read out the list of candidates drawn up by the church council. He shall also read out articles 4, 6 and 12 of these rules. He shall satisfy himself as to the accuracy of the number of members participating in the election and the number of votes cast. The official report of this election shall be entered in the ordinary minute book of the church council and duly approved and signed.

**App's interpretation:** procedural. The app supports the "official report" requirement via the **Minutes DOCX** export (admin → Manage → "Export Minutes"). The DOCX includes per-round attendance, ballot counts, candidate tallies, and elected results. The secretary still reads the candidates and articles aloud at the meeting; the app does not automate that step.

---

## Article 6

**Rule text:**

> The candidates who receive the most votes will be declared elected, provided that:
>
> a) they receive a number of votes greater than half the valid votes cast divided by the number of vacancies, and
>
> b) the number of votes they receive is equal to or greater than two-fifths of the number of people who participated in the election.

**App's interpretation:**

- **Article 6a** is implemented in [`election_rules.calculate_thresholds`](../election_rules.py) as `threshold_6a = valid_votes_cast / (2 * vacancies)`. A candidate must receive **strictly more than** this threshold (per the wording "greater than"). The denominator uses **Reading A** (see provenance below): `valid_votes_cast` is the per-office sum of ticks recorded for candidates in that office. Blank ballots/slots and spoilt ballots do not count.
- **Article 6b** uses `threshold_6b = ceil(participants * 2 / 5)`. A candidate must receive **at least** this number (per "equal to or greater than"). Fractions are rounded up per Article 7. `participants` is in-person attendance plus postal voters (postal counted in round 1 only).
- "Candidates who receive the most votes" is implemented in [`election_rules.resolve_elected_status`](../election_rules.py): only the top-N threshold-passers by vote count are elected, where N is the number of vacancies remaining for the office. Candidates tied at the boundary are not elected and proceed to a runoff (see Article 7).

**Decision provenance — Article 6a "valid votes cast"** (April 2026):

The phrase "half the valid votes cast" is ambiguous between three readings. The maintainer raised the question with the chairman after a close round-2 result exposed the difference. Earlier the chairman had observed that the rule comes from a time when blank ballots were potentially common, suggesting blanks should count toward the denominator. The maintainer subsequently asked, with a worked example for one Elder vacancy and four candidates, which interpretation council follows. The chairman's reply in writing:

> I have always understood that a valid voter is that which is for a candidate. Whilst a blank may be choice (and perhaps even with reason ie no knowledge of the candidates), it is not a vote "for". So my understanding is that "A" is the correct application.

Council's confirmed reading is therefore: **only ticks for candidates count as "valid votes cast"** (Reading A). Blank ballots are deliberate abstentions but they are not votes "for" any candidate; spoilt ballots fail Article 7's "clearly indicates a valid choice" test. Both are excluded from the Article 6a denominator. Note that Article 6b independently provides a participation floor (40% of attendees) which is the safety net against weak-support outcomes when many brothers abstain.

---

## Article 7

**Rule text:**

> Voting papers wrongly filled in are valid to the extent to which they clearly indicate a valid choice. Thus if two names are required, but only one is marked, then one valid vote is recorded.
>
> Before the votes are counted, the minimum number of votes required for a candidate to be elected must be determined (two-fifths of the number of people who participated in the election). Fractions will be rounded upwards.
>
> If, after voting, the number of candidates elected is insufficient to fill the vacancies, an additional ballot will be held between those candidates who did not receive a sufficient number of votes. If, in any subsequent ballot, no additional candidate is elected, the number of candidates from which a choice is to be made shall be reduced to twice the number of vacancies remaining to be filled by eliminating those candidates who gained the least votes.

**App's interpretation:**

- **Partial / wrongly-filled ballots.** Digital ballots cannot be "wrongly filled" because the UI enforces `max_selections` per office. Partial ballots (under-voting on multi-vacancy offices) are accepted with a warning and the marked candidates each receive one valid vote, per the "if two names are required, but only one is marked, then one valid vote is recorded" example. Paper ballots that are wrongly filled (over-voted, illegible) are recorded as **spoilt** ballots via the per-office spoilt-count input on the Paper Votes admin page; they are stored in the `office_spoilt_ballots` table and are excluded from "valid votes cast" by definition.
- **Two-fifths floor.** Implemented in [`election_rules.calculate_thresholds`](../election_rules.py) as `math.ceil(participants * 2 / 5)`. See Article 6b above.
- **Subsequent ballot.** When the chairman closes a round and not enough candidates were elected, the manage page offers a "Next Round" action. The chairman selects which candidates carry forward. The app's UI allows continuing with the same slate or eliminating candidates per the rule's reduction-to-twice-the-vacancies clause. Eliminating "candidates who gained the least votes" is a manual step in the chairman's flow; the app shows vote tallies but does not auto-eliminate. This places the procedural judgement with the chairman, who can also apply Article 13 deviation.

---

## Article 8

**Rule text:**

> The church council shall appoint each elected candidate at the first church council meeting after the election, and shall inform him of his appointment. If the appointee asks to be relieved of his appointment, and the church council grants this request, the church council will appoint the candidate with the next highest number of votes, provided that he has received more than one half of the valid votes cast. (Art. 6a).

**App's interpretation:** outside scope. The "next highest" replacement decision is a council action that happens after this app's involvement. The minutes export records full tallies, which council can use to identify the next candidate. The app does not automate the decline/replace flow.

---

## Article 9

**Rule text:**

> The names of the appointed brothers shall be publicly announced to the congregation so that the congregation may give its approbation. If no valid objections are lodged, the appointees shall be ordained according to the Form for the Ordination of Elders and Deacons.

**App's interpretation:** outside scope.

---

## Article 10

**Rule text:**

> Retiring office-bearers shall not be re-electable unless the church council deems it to be in the interest of the Church that they remain in church council. In this case the church council may either place their names on the list of candidates which is submitted to the congregation, or church council may extend their term of office.

**App's interpretation:** the candidate model has a `retiring_office_bearer` flag (boolean). Eligibility is decided by council; the flag is informational and shown alongside the candidate's name on the ballot setup page. The app does not enforce or block based on this flag.

---

## Article 11

**Rule text:**

> The church council shall decide when interim vacancies shall be filled. When interim election is held, the church council shall adhere to the stipulations in these rules except where they refer to specific calendar dates.
>
> Those elected to fill interim vacancies will serve for the remainder of the terms of the brothers they replaced. If however that period is less than one year their term shall be extended by the normal period of three years.

**App's interpretation:** the elections table has an `is_interim` flag and an `interim_term_info` text field. When interim mode is on, the app skips calendar-date validation. Term-length adjustment (the "less than one year" rule) is recorded in `interim_term_info` as free text by the chairman; the app does not compute it.

---

## Article 12

**Rule text:**

> Objections of a formal nature against procedure at the election shall be lodged at the same meeting.

**App's interpretation:** procedural. The minutes DOCX has a free-text section for objections.

---

## Article 13

**Rule text:**

> If at any time the church council considers it desirable to deviate from these rules it may do so, as long as it does not deviate from articles 1, 5 and 12.

**App's interpretation:** the app provides explicit overrides where deviation is realistic:

- **Slate size** (Article 2): `confirm_slate_override` on the office setup form.
- **Round 1 attendance** during a demo: `seed_demo.py` pre-sets attendance to the code count.

The app does not enforce non-deviation from articles 1, 5, and 12 because those articles are procedural rather than algorithmic; deviation would happen outside the app.

---

## Decision log

| Date | Article | Decision | Source |
|------|---------|----------|--------|
| April 2026 | 6a | "Valid votes cast" means the per-office sum of candidate ticks. Blank ballots and spoilt ballots are excluded from the denominator. | Email correspondence with the chairman; reproduced (anonymized) below. |

### Appendix: Article 6a decision correspondence (anonymized)

**From the maintainer to the chairman, April 2026:**

> Subject: Question about Article 6a — which interpretation?
>
> I'm trying to settle how the voting app should apply Article 6a. Here is a hypothetical Round 1 to make the question concrete.
>
> Imagine: 100 brothers attend. Two Elder seats. Four candidates on the slate. Each ballot can mark up to two names. Result:
>
> - Br. A: 60 ticks
> - Br. B: 47 ticks
> - Br. C: 35 ticks
> - Br. D: 35 ticks
> - Spoilt ballots (e.g. three ticks where two were allowed): 2
>
> The remaining 98 valid ballots produced 177 total ticks. Each valid ballot offered up to 2 vote slots, so 98 × 2 = 196 valid slots in total. Of those, 177 were used and 19 were left blank — a "blank" being either a fully unmarked ballot or one tick where two were allowed.
>
> Article 6a says the elected brother must receive "more than half the valid votes cast divided by the number of vacancies". Spoilt ballots are not valid by definition. The remaining question is what "valid votes cast" means:
>
> A. Only ticks for candidates count. Total = 177. Threshold = 177 / (2 × 2) = 44.25. Br. A (60) and Br. B (47) pass. Br. C (35) and Br. D (35) fail. Both seats filled.
>
> B. All valid vote slots count (used and blank). Total = 196. Threshold = 196 / (2 × 2) = 49. Br. A (60) passes. Br. B (47), C (35), D (35) fail. One seat filled, Round 2 needed for the second.
>
> Which interpretation does council follow?

**Chairman's reply:**

> I have always understood that a valid voter is that which is for a candidate. Whilst a blank may be choice (and perhaps even with reason ie no knowledge of the candidates), it is not a vote "for". So my understanding is that "A" is the correct application.

The app implements **Reading A** as a result of this confirmation.
