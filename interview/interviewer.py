from openai import OpenAI
import config


class Interviewer:
    def __init__(
        self,
        resume_text: str,
        job_description: str,
        candidate_name: str = "there"
    ):
        """
        Initialises the Interviewer for a single call session.

        Args:
            resume_text:     Full text of the candidate's resume.
            job_description: The job description to interview against.
            candidate_name:  Candidate's name used in the opening greeting.
                             Defaults to "there" if not provided.

        State:
            conversation_history  — running list of GPT messages (user/assistant turns).
            question_count        — number of questions asked so far (max 5).
            is_complete           — set to True when the interview ends.
            interview_started     — False until the candidate confirms availability.
            covered_topics        — short topic labels extracted after each question,
                                    fed back into the system prompt to prevent repeats.
            _last_filler_index    — tracks the last filler used so the same one is
                                    never played twice in a row.
        """
        self.client = OpenAI(api_key=config.OPENAI_API_KEY)
        self.model = "gpt-4o-mini"
        self.resume_text = resume_text
        self.job_description = job_description
        self.candidate_name = candidate_name
        self.conversation_history = []
        self.question_count = 0
        self.is_complete = False
        self.interview_started = False
        self._last_filler_index = -1
        self.covered_topics = []

    def get_opening_message(self) -> str:
        """
        Returns the fixed first line spoken when the call connects.
        Confirms the right person answered, frames the call as a
        telephonic interview round, and asks for availability consent
        before starting. Hardcoded for speed and consistency.
        """
        return (
            f"Hello, am I speaking with {self.candidate_name}? "
            "This is a telephonic interview round for the job post "
            "you applied for. "
            "Is this a good time to speak for about 10 minutes?"
        )

    def handle_availability_response(self, text: str) -> str:
        """
        Routes the candidate's first reply after the opening greeting.

        Checks for positive or negative availability signals using keyword
        lists that cover English and common Hindi responses. Evaluated in
        this order to avoid false positives:
          1. Negative match  → sets is_complete, returns a goodbye.
          2. Positive match  → sets interview_started, generates and
                               returns the first interview question.
          3. No match        → asks the candidate to repeat themselves.

        Called by call_manager before interview_started is True.
        All subsequent replies go to generate_response() instead.
        """
        text_lower = text.lower().strip()

        positive = [
            "yes", "yeah", "sure", "okay", "ok", "yep",
            "go ahead", "good time", "ready", "fine",
            "absolutely", "of course", "please", "proceed",
            "start", "begin", "lets go", "let's go", "haan",
            "han", "bilkul", "theek", "theek hai"
        ]
        negative = [
            "no", "busy", "not now", "bad time", "later",
            "cant", "cannot", "call back", "not a good",
            "nahi", "nhi", "abhi nahi"
        ]

        is_negative = any(word in text_lower for word in negative)
        is_positive = any(word in text_lower for word in positive)

        if is_negative:
            self.is_complete = True
            return (
                "No problem at all. We will reach out to schedule "
                "at a more convenient time. Have a good day."
            )

        if is_positive:
            self.interview_started = True
            first_question = self._generate_first_question()
            return f"Perfect. Let us get started. {first_question}"

        return (
            "Sorry, I missed that. "
            "Is this a good time to proceed with the interview?"
        )

    def _build_system_prompt(self) -> str:
        """
        Builds the GPT system prompt dynamically before each API call.

        Injects three live values so the prompt stays accurate across turns:
          - covered_topics: 3-word labels of topics already asked, so GPT
            can avoid repeating them.
          - job_description: full JD text to drive question selection.
          - resume_text: first 3000 chars of the resume to calibrate
            question difficulty against candidate experience.

        The prompt instructs GPT to follow a 5-step question selection
        process (read JD → read resume → find gap → pick uncovered topic →
        ask calibrated question) and rotate across five question types
        (Concept, Situational, Design, Trade-off, Tool-specific).
        """
        asked_summary = (
            "\n".join(f"- {t}" for t in self.covered_topics)
            if self.covered_topics else "None yet"
        )

        return f"""You are a senior engineer conducting a telephonic \
technical screening round for the following role.

YOUR ONLY JOB is to ask ONE specific technical question per turn.

STRICT RULES:
- Ask ONE question. Nothing else.
- Do NOT reveal you are an AI.
- Do NOT give feedback on answers.
- Do NOT summarise what the candidate said.
- Do NOT use filler like "let me think" or "interesting".
- Keep each question under 35 words.
- After exactly 5 questions say INTERVIEW_COMPLETE followed \
by a brief natural closing line.

HOW TO PICK THE NEXT QUESTION:
Step 1 — Read the job description carefully.
         List every technology, tool, concept, and skill mentioned.

Step 2 — Read the candidate resume carefully.
         Note what they claim to know and what they have built.

Step 3 — Compare. Identify gaps between what the JD needs \
and what the resume shows.

Step 4 — Pick the most important uncovered topic from the JD
         that has NOT been asked yet.

Step 5 — Ask a specific, technical question about that topic
         calibrated to candidate experience:

         Candidate experience < required:
         Ask foundational questions.
         Example: "Can you explain what a REST API is and \
how you have used one in a project?"

         Candidate experience matches required:
         Ask applied questions about real work.
         Example: "Walk me through how you handled a \
database performance issue in production."

         Candidate experience > required:
         Ask architectural and trade-off questions.
         Example: "How would you design a distributed \
job queue that handles 100k tasks per minute?"

QUESTION TYPES TO ROTATE THROUGH (pick a different type each time):
1. Concept — test if they understand how something works
   "How does indexing improve query performance in PostgreSQL?"

2. Situational — test real experience
   "Describe a time you had to debug a memory leak in production."

3. Design — test how they think
   "How would you design an API rate limiter from scratch?"

4. Trade-off — test depth
   "When would you choose a message queue over a direct API call?"

5. Tool-specific — test hands-on knowledge of JD tools
   "What is the difference between @RestController and \
@Controller in Spring Boot?"

QUESTIONS ALREADY ASKED — do NOT repeat these topics:
{asked_summary}

JOB DESCRIPTION:
{self.job_description}

CANDIDATE RESUME:
{self.resume_text[:3000]}

Questions asked so far: {self.question_count} of 5
"""

    def _generate_first_question(self) -> str:
        """
        Generates the warm-up opening question for the interview.

        Called once by handle_availability_response() after the candidate
        confirms they are available. Uses a separate user prompt that
        explicitly requests an open-ended background question, so the first
        turn always feels like a natural conversation starter rather than a
        deep technical question.
        """
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": self._build_system_prompt()
                },
                {
                    "role": "user",
                    "content": (
                        "Generate only the first interview question. "
                        "It should be an open ended warm-up question "
                        "about their overall background and experience. "
                        "One sentence only. No intro, just the question."
                    )
                }
            ],
            max_tokens=80,
            temperature=0.7
        )
        return response.choices[0].message.content.strip()

    def _generate_next_question(self) -> str:
        """
        Generates a replacement question when the candidate signals they
        don't know the answer (detected by is_dont_know_response()).

        Passes the full conversation history alongside the system prompt so
        GPT knows which topics have already been attempted, then explicitly
        asks for a question on a different topic. Temperature is set to 0.8
        (slightly higher than the main flow) to encourage variety.
        """
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": self._build_system_prompt()
                },
                {
                    "role": "user",
                    "content": (
                        "The candidate did not know the answer to "
                        "the previous question. Ask a different question "
                        "on a different topic from the job description. "
                        "One sentence only. No intro, just the question."
                    )
                }
            ] + self.conversation_history,
            max_tokens=80,
            temperature=0.8
        )
        return response.choices[0].message.content.strip()

    def _extract_topic(self, question: str) -> str:
        """
        Extracts a 3-word-or-less topic label from a generated question.

        Called immediately after each question is produced in generate_response().
        The label is appended to covered_topics and injected into the next
        system prompt under "QUESTIONS ALREADY ASKED" so GPT never revisits
        the same area. Uses temperature=0 for deterministic, consistent labels.
        """
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Extract the core technical topic from this "
                        f"interview question in 3 words or less. "
                        f"Return ONLY the topic, nothing else.\n\n"
                        f"Question: {question}"
                    )
                }
            ],
            max_tokens=10,
            temperature=0
        )
        return response.choices[0].message.content.strip().lower()

    def _get_filler(self) -> str:
        """
        Returns a short acknowledgement phrase to play before each question.

        Picks randomly from a pool of 10 fillers but excludes the one used
        on the previous turn (_last_filler_index) so the same phrase is never
        heard twice in a row. Gives the interview a more natural, human-paced
        rhythm without repeating verbal tics.
        """
        import random
        fillers = [
            "Okay.",
            "Got it.",
            "Sure.",
            "Right.",
            "Alright.",
            "Okay, moving on.",
            "Sure, next question.",
            "Alright, let us continue.",
            "Got it, moving ahead.",
            "Okay, next one.",
        ]
        available = [
            (i, f) for i, f in enumerate(fillers)
            if i != self._last_filler_index
        ]
        index, filler = random.choice(available)
        self._last_filler_index = index
        return filler

    def is_dont_know_response(self, text: str) -> bool:
        """
        Returns True if the candidate's reply signals they don't know
        or want to skip the current question.

        Matches against a phrase list covering English expressions of
        uncertainty and Hindi equivalents (nahi pata, yaad nahi, etc.).
        Checked at the top of generate_response() before is_sufficient_answer(),
        because skip phrases like "pass" or "no idea" are short and would
        otherwise be rejected by the word-count gate.
        """
        text_lower = text.lower().strip()

        phrases = [
            "don't know", "dont know", "do not know",
            "not aware", "not sure", "no idea",
            "i forgot", "can't remember", "cannot remember",
            "cant remember", "i forget", "not familiar",
            "never used", "never worked", "no experience with",
            "haven't used", "havent used", "not worked on",
            "not worked with", "nahi pata", "nahi malum",
            "pata nahi", "malum nahi", "yaad nahi",
            "blank", "skip", "next question", "pass"
        ]

        return any(phrase in text_lower for phrase in phrases)

    def is_sufficient_answer(self, text: str) -> bool:
        """
        Returns True if the candidate's reply is substantive enough to
        warrant generating the next interview question.

        Requires at least 5 total words AND at least 4 non-filler words.
        The filler set catches one-word acknowledgements ("yes", "okay",
        "hmm") that Deepgram occasionally emits mid-answer. Returning False
        causes generate_response() to ask the candidate to elaborate rather
        than counting the turn as a completed answer.
        """
        words = text.split()
        if len(words) < 5:
            return False
        filler_only = {"yes", "no", "okay", "ok", "sure", "yeah",
                       "um", "uh", "hmm", "right", "fine"}
        non_filler = [w for w in words if w.lower() not in filler_only]
        return len(non_filler) >= 4

    def generate_response(self, candidate_utterance: str) -> str:
        """
        Main response loop — decides what the interviewer says after each
        candidate answer during the live interview.

        Decision order:
          1. is_dont_know_response() → play a skip filler, call
             _generate_next_question(), and move on. Increments
             question_count without adding the skipped turn to history.
          2. is_sufficient_answer() → if the reply is too short, ask the
             candidate to elaborate. Does not increment question_count.
          3. Normal flow → append candidate turn to conversation_history,
             increment question_count, call GPT, prepend a filler phrase,
             extract and record the topic, append the reply to history.

        Signals end of interview:
          - If GPT returns INTERVIEW_COMPLETE, sets is_complete = True and
            strips the sentinel before returning the closing line.
          - If question_count reaches 5 on a skip, sets is_complete = True
            and returns a closing message directly.

        The caller (call_manager) checks is_complete after each call and
        hangs up the call with a short delay if True.
        """
        if self.is_dont_know_response(candidate_utterance):
            import random
            self.question_count += 1
            print(f"[Interviewer] Candidate skipped — moving on")

            skip_fillers = [
                "No worries, let us move on.",
                "That is fine, moving to the next one.",
                "No problem at all, next question.",
                "Okay, let us skip that one.",
                "Sure, let us move ahead.",
            ]
            filler = random.choice(skip_fillers)

            if self.question_count >= 5:
                self.is_complete = True
                return (
                    f"{filler} That is all the questions I had. "
                    "Thank you for your time today. "
                    "The team will be in touch with next steps. "
                    "Have a great day."
                )

            next_question = self._generate_next_question()
            return f"{filler} {next_question}"

        if not self.is_sufficient_answer(candidate_utterance):
            print(f"[Interviewer] Short answer, prompting for more: '{candidate_utterance}'")
            return "Could you tell me a bit more about that?"

        self.conversation_history.append({
            "role": "user",
            "content": candidate_utterance,
        })
        self.question_count += 1

        messages = [
            {
                "role": "system",
                "content": self._build_system_prompt()
            }
        ] + self.conversation_history

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=120,
            temperature=0.9,
        )

        raw_question = response.choices[0].message.content.strip()

        if "INTERVIEW_COMPLETE" in raw_question:
            self.is_complete = True
            reply = raw_question.replace("INTERVIEW_COMPLETE", "").strip()
            if not reply:
                reply = (
                    "That is all the questions I have for you today. "
                    "Thank you so much for your time. "
                    "The hiring team will be in touch with next steps. "
                    "Have a great day!"
                )
        else:
            filler = self._get_filler()
            reply = f"{filler} {raw_question}"

            topic = self._extract_topic(raw_question)
            self.covered_topics.append(topic)
            print(f"[Interviewer] Topic covered: {topic}")

        self.conversation_history.append({
            "role": "assistant",
            "content": reply,
        })

        print(f"[Interviewer] Q{self.question_count}: {reply[:80]}...")
        return reply

    def get_full_transcript(self) -> str:
        """
        Returns the full conversation as a human-readable transcript.

        Formats every turn in conversation_history as "Interviewer: ..."
        or "Candidate: ..." joined by blank lines. Called at the end of
        the WebSocket session in call_manager and passed to the reporter
        module to generate the final candidate score and summary.
        Note: the availability exchange is not part of conversation_history
        and will not appear in the transcript.
        """
        lines = []
        for msg in self.conversation_history:
            role = "Interviewer" if msg["role"] == "assistant" else "Candidate"
            lines.append(f"{role}: {msg['content']}")
        return "\n\n".join(lines)
