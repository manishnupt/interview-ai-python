from openai import OpenAI
import config


class Interviewer:
    def __init__(
        self,
        resume_text: str,
        job_description: str,
        candidate_name: str = "there"
    ):
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
        return (
            f"Hello, am I speaking with {self.candidate_name}? "
            "This is a telephonic interview round for the job post "
            "you applied for. "
            "Is this a good time to speak for about 10 minutes?"
        )

    def handle_availability_response(self, text: str) -> str:
        """
        Called after the opening message to check if
        the candidate confirmed availability.
        Returns the first interview question if yes,
        or a polite goodbye if no.
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
        Generates the first question separately so it
        uses candidate experience level to set the right tone.
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
        words = text.split()
        if len(words) < 5:
            return False
        filler_only = {"yes", "no", "okay", "ok", "sure", "yeah",
                       "um", "uh", "hmm", "right", "fine"}
        non_filler = [w for w in words if w.lower() not in filler_only]
        return len(non_filler) >= 4

    def generate_response(self, candidate_utterance: str) -> str:
        """
        Given what the candidate just said, decide what the interviewer says next.

        Returns the text response to speak.
        Sets self.is_complete = True when GPT signals INTERVIEW_COMPLETE.
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
        Returns the full conversation as a readable transcript
        for the reporter to generate the final score and summary.
        """
        lines = []
        for msg in self.conversation_history:
            role = "Interviewer" if msg["role"] == "assistant" else "Candidate"
            lines.append(f"{role}: {msg['content']}")
        return "\n\n".join(lines)
