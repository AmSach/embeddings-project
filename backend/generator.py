import os
import requests
import json
import torch
from transformers import pipeline, AutoTokenizer, AutoModelForCausalLM
from typing import List, Dict, Any, Optional

class GeopoliticalGenerator:
    def __init__(self, model_name: str = "Qwen/Qwen2.5-1.5B-Instruct"):
        self.gemini_key = os.getenv("GEMINI_API_KEY")
        self.openai_key = os.getenv("OPENAI_API_KEY")
        self.groq_key = os.getenv("GROQ_API_KEY")
        self.prefer_ollama = os.getenv("PREFER_OLLAMA", "false").lower() == "true"
        self.ollama_model = os.getenv("OLLAMA_MODEL", "qwen3.5:9b")
        
        # Local model state (loaded lazily on first local call to save memory at startup)
        self.local_model_name = model_name
        self.tokenizer = None
        self.model = None
        self.pipe = None
        
        print("Generator initialized. APIs available: "
              f"Gemini={bool(self.gemini_key)}, Groq={bool(self.groq_key)}, OpenAI={bool(self.openai_key)}, "
              f"Ollama(prefer={self.prefer_ollama}, model={self.ollama_model})")

    def _call_gemini_api(self, prompt: str, system_instruction: str) -> Optional[str]:
        """Calls Google Gemini API via direct HTTP request."""
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={self.gemini_key}"
        headers = {"Content-Type": "application/json"}
        payload = {
            "contents": [{
                "parts": [{
                    "text": f"{system_instruction}\n\nUser Request: {prompt}"
                }]
            }],
            "generationConfig": {
                "temperature": 0.4,
                "topP": 0.95,
                "maxOutputTokens": 8192
            }
        }
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            if response.status_code == 200:
                data = response.json()
                return data["candidates"][0]["content"]["parts"][0]["text"]
            else:
                print(f"Gemini API returned error code {response.status_code}: {response.text}")
                return None
        except Exception as e:
            print(f"Error calling Gemini API: {e}")
            return None

    def _call_openai_api(self, prompt: str, system_instruction: str) -> Optional[str]:
        """Calls OpenAI API via direct HTTP request."""
        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.openai_key}"
        }
        payload = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.4,
            "max_tokens": 8192
        }
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            if response.status_code == 200:
                data = response.json()
                return data["choices"][0]["message"]["content"]
            else:
                print(f"OpenAI API returned error code {response.status_code}: {response.text}")
                return None
        except Exception as e:
            print(f"Error calling OpenAI API: {e}")
            return None

    def _call_groq_api(self, prompt: str, system_instruction: str) -> Optional[str]:
        """Calls Groq API (free tier: llama-3.3-70b-versatile). Fast LPU inference."""
        import time as _time
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.groq_key}"
        }
        payload = {
            "model": "llama-3.3-70b-versatile",
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.4,
            "max_tokens": 8192,
            "stream": False
        }
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=120)
            if response.status_code == 200:
                data = response.json()
                result = data["choices"][0]["message"]["content"]
                # Groq rate limit: wait between calls to stay within free tier
                usage = data.get("usage", {})
                total_tokens = usage.get("total_tokens", 0)
                print(f"  Groq: {total_tokens} tokens used ({usage.get('completion_tokens', 0)} generated)")
                # Free tier = ~6000 tokens/min for 70B, so wait proportionally
                wait_secs = max(5, (total_tokens / 6000) * 60)
                print(f"  Groq rate-limit pause: {wait_secs:.0f}s")
                _time.sleep(wait_secs)
                return result
            elif response.status_code == 429:
                # Rate limited — wait and retry once
                print(f"Groq rate limited. Waiting 60s and retrying...")
                _time.sleep(60)
                response = requests.post(url, headers=headers, json=payload, timeout=120)
                if response.status_code == 200:
                    return response.json()["choices"][0]["message"]["content"]
                print(f"Groq retry also failed: {response.status_code}")
                return None
            else:
                print(f"Groq API error {response.status_code}: {response.text[:200]}")
                return None
        except Exception as e:
            print(f"Error calling Groq API: {e}")
            return None

    def _call_ollama_api(self, prompt: str, system_instruction: str, model_name: str = "qwen3.5:9b") -> Optional[str]:
        """Calls local Ollama API for text generation."""
        url = "http://127.0.0.1:11434/api/chat"
        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt}
            ],
            "options": {
                "temperature": 0.4
            },
            "stream": False
        }
        try:
            response = requests.post(url, json=payload, timeout=300)
            if response.status_code == 200:
                return response.json()["message"]["content"]
            else:
                print(f"Ollama API returned error code {response.status_code}: {response.text}")
                return None
        except Exception as e:
            print(f"Error calling Ollama API: {e}")
            return None

    def _load_local_model(self):
        """Loads the local Qwen model lazily into GPU/RAM."""
        if self.pipe is not None:
            return
        
        print(f"Loading local model '{self.local_model_name}' (device_map=auto)...")
        device = "cuda" if torch.cuda.is_available() else "cpu"
        
        self.tokenizer = AutoTokenizer.from_pretrained(self.local_model_name)
        
        # Load in half precision for GPU execution to save VRAM
        if device == "cuda":
            self.model = AutoModelForCausalLM.from_pretrained(
                self.local_model_name,
                torch_dtype=torch.float16,
                device_map="auto"
            )
        else:
            self.model = AutoModelForCausalLM.from_pretrained(self.local_model_name)
            
        self.pipe = pipeline(
            "text-generation", 
            model=self.model, 
            tokenizer=self.tokenizer,
            max_new_tokens=4096,
            temperature=0.4,
            do_sample=True
        )
        print("Local model loaded successfully!")

    def _call_local_model(self, prompt: str, system_instruction: str) -> str:
        """Runs inference locally using HuggingFace pipeline."""
        self._load_local_model()
        
        messages = [
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": prompt}
        ]
        
        # Format prompt with chat template
        formatted_prompt = self.tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        
        outputs = self.pipe(formatted_prompt)
        raw_out = outputs[0]["generated_text"]
        
        # Extract assistant response (after the last generation prompt)
        split_marker = "<|im_start|>assistant\n"
        if split_marker in raw_out:
            return raw_out.split(split_marker)[-1].split("<|im_end|>")[0].strip()
        
        return raw_out

    def generate(self, prompt: str, system_instruction: str) -> str:
        """Dispatches text generation based on available API keys or local fallback."""
        # Enforce inline ground-truth citations pointing directly to crawled URLs
        citation_rule = (
            "\n\nCRITICAL RETRIEVAL CITATION REQUIREMENT:\n"
            "You MUST ground all factual assertions, legal references, and strategic recommendations in the provided retrieved context. "
            "Whenever you reference a fact, treaty, case, or event from the context, you MUST immediately insert an inline Markdown link "
            "citing that source in the exact format: [Source Title](Source URL). Use the exact URLs and Titles provided in the context. "
            "Do NOT invent or hallucinate URLs. Every major paragraph or claim in your response should have at least one inline hyperlink citation."
        )
        system_instruction += citation_rule

        # 0. Try Ollama if explicitly preferred
        if self.prefer_ollama:
            print(f"Prefer Ollama is enabled. Trying local Ollama model: {self.ollama_model}...")
            res = self._call_ollama_api(prompt, system_instruction, model_name=self.ollama_model)
            if res:
                return res
            print("Ollama call failed or returned empty. Proceeding with standard backends...")

        # 1. Try Gemini
        if self.gemini_key:
            res = self._call_gemini_api(prompt, system_instruction)
            if res:
                return res

        # 2. Try Groq (free, fast, good quality)
        if self.groq_key:
            res = self._call_groq_api(prompt, system_instruction)
            if res:
                return res

        # 3. Try OpenAI
        if self.openai_key:
            res = self._call_openai_api(prompt, system_instruction)
            if res:
                return res

        # 4. Fallback to Ollama (first local fallback if not already tried)
        if not self.prefer_ollama:
            try:
                # Quick check if Ollama is running and has any models
                test_res = requests.get("http://127.0.0.1:11434/api/tags", timeout=2)
                if test_res.status_code == 200:
                    models_list = [m["name"] for m in test_res.json().get("models", [])]
                    target_model = self.ollama_model
                    available = any(target_model in m or m in target_model for m in models_list)
                    if not available and models_list:
                        target_model = models_list[0]
                        print(f"Target Ollama model '{self.ollama_model}' not found in {models_list}. Using '{target_model}' instead.")
                        available = True
                    
                    if available:
                        print(f"Ollama is running. Generating response using '{target_model}'...")
                        res = self._call_ollama_api(prompt, system_instruction, model_name=target_model)
                        if res:
                            return res
            except Exception as ollama_err:
                print(f"Ollama check/call failed: {ollama_err}")

        # 5. Fallback to Local Transformers Model
        print("No API keys available or API/Ollama calls failed. Falling back to local transformers model generation...")
        try:
            return self._call_local_model(prompt, system_instruction)
        except Exception as local_err:
            return f"Error running local text generation: {local_err}. Please ensure model weights are reachable and GPU/RAM is sufficient."

    # --- Model UN Specific Modes ---

    def draft_speech(self, query: str, context_chunks: List[Dict[str, Any]], country: str = "the State") -> str:
        """Drafts a GSL or Mod-Caucus speech optimized for persuasive framing and diplomatic vocabulary."""
        system_instruction = (
            "You are an elite geopolitical strategist and speechwriter for a Model UN Ambassador. "
            "Your writing style is highly formal, strategic, and persuasive. "
            "Do NOT optimize for objective academic 'truth'. Optimize for persuasive argument retrieval, "
            "sovereignty protection, strategic framing, and formal diplomatic rhetoric. "
            "Write in the active, formal voice (using 'The delegation of [Country]...')."
        )

        # Compile chunk references
        context_str = ""
        for i, chunk in enumerate(context_chunks):
            context_str += f"Source [{i+1}] (Trust: {chunk['trust_score']:.2f}, Title: {chunk['title']}):\n{chunk['text']}\n\n"

        prompt = f"""
Country Representation: {country}
User Debate Target: {query}

Retrieved Geopolitical Context:
{context_str}

TASK:
Draft a comprehensive debater briefing sheet. You MUST generate two distinct sections:

1. **## 📘 Geopolitical Briefing & Educational Context**
   Explain the historical and legal background of this dispute/topic to the user. Describe who the main stakeholders are, the international law hooks involved (such as specific articles of UNCLOS, bilateral treaties, or UN Charter parameters), and explain the strategic reasoning behind why we must frame the issue in a certain way. Educate the user thoroughly.

2. **## 🎤 GSL Debate Speech**
   Write a highly structured, 90-second debate speech (approximately 200-250 words) for the Ambassador of {country}.
   - **Strategic Framing**: Frame the issue to favor {country}'s geopolitical interest. Turn vulnerabilities into procedural complaints or sovereign deflections.
   - **Argument Retrieval**: Integrate specific facts or legal hooks from the retrieved Sources above.
   - **Diplomatic Phrasing**: Use powerful Model UN vocabulary (e.g., 'we call upon the body', 'grave concern', 'unilateral overreach', 'in accordance with UNCLOS Article...').
   - **Actionable Operative Hook**: Close with a strong statement on what resolutions the delegation will support.

Draft the briefing and speech now:
"""
        return self.generate(prompt, system_instruction)

    def draft_counterargument(self, accusation: str, context_chunks: List[Dict[str, Any]], country: str = "the State") -> str:
        """Drafts a defensive Shield (procedural/sovereignty deflections) and offensive Sword (reciprocal accusations)."""
        system_instruction = (
            "You are a battle-hardened diplomat in a high-stakes Model UN Crisis Committee. "
            "Your objective is to defend your country against serious accusations and immediately counter-attack. "
            "You engage in 'structured persuasive warfare'. Do not admit fault. Use international law, "
            "procedural precedents, and raw geopolitical hypocrisies to deflect and retaliate."
        )

        context_str = ""
        for i, chunk in enumerate(context_chunks):
            context_str += f"Source [{i+1}] (Trust: {chunk['trust_score']:.2f}, Title: {chunk['title']}):\n{chunk['text']}\n\n"

        prompt = f"""
Country Representation: {country}
Accusation/Clash Target: {accusation}

Retrieved Geopolitical Context:
{context_str}

TASK:
Produce a strategic Debate Clash sheet containing:

1. **## 📘 Legal & Historical Clash Analysis**
   Explain the background of the clash topic, the specific legal structures involved (e.g., UN Charter Articles, treaty frameworks), and the underlying facts of the accusation. Educate the user on why this attack is being made and the strategic leverage we have.

2. **## 🛡️ The Shield (Deflection & Defense)**
   Draft a 3-point formal diplomatic defense. Quote international treaties (e.g. UN Charter Article 2(7) regarding sovereign domestic jurisdiction, or UNCLOS provisions) and use source facts to deflect the accusation as procedural overreach, fabrications, or lacking legal basis.

3. **## ⚔️ The Sword (Counter-Attack)**
   Draft a 3-point offensive retaliation. Point out specific hypocrisies, double standards, or military/security transgressions committed by the accusers (or their allies) using the retrieved Sources.

4. **## 💬 Clash Talking Points**
   Provide 3 short, punchy, sleep-deprived-friendly soundbites that can be delivered in a 30-second Right of Reply.

Draft the Clash Sheet now:
"""
        return self.generate(prompt, system_instruction)

    def draft_resolution_clauses(self, crisis_scenario: str, context_chunks: List[Dict[str, Any]], country: str = "the State") -> str:
        """Drafts highly structured, formal UN Resolution Preambulatory and Operative Clauses."""
        system_instruction = (
            "You are a legal draftsperson for a Model UN coalition. "
            "You write in the strict, sacred, and formal style of UN Resolutions. "
            "Use standard italicized/capitalized preambulatory phrases (e.g., Guided by, Recalling, Expressing grave concern) "
            "and numbered operative clauses (e.g., 1. Condemns, 2. Urges, 3. Decides, 4. Recommends). "
            "Your outputs must look ready to compile directly into a draft resolution."
        )

        context_str = ""
        for i, chunk in enumerate(context_chunks):
            context_str += f"Source [{i+1}] (Trust: {chunk['trust_score']:.2f}, Title: {chunk['title']}):\n{chunk['text']}\n\n"

        prompt = f"""
Country / Coalition Representation: {country}
Crisis / Resolution Topic: {crisis_scenario}

Retrieved Geopolitical Context:
{context_str}

TASK:
Draft formal UN Resolution Clauses designed to address this crisis while securing the strategic interests of {country}.

You MUST generate the following sections:

1. **## 📘 Resolution Rationale & Framework Briefing**
   Educate the user on why this crisis occurred, the historical precedents of similar resolutions, what international legal frameworks we are invoking (e.g. UN Charter, UNCLOS clauses), and why this set of resolutions serves our coalition's security strategy.

2. **## 📝 Preambulatory Clauses**
   Draft 3 clauses introducing the context, referencing specific international frameworks retrieved from the Sources. Use standard preambulatory words (e.g. Recalling, Emphasizing, Expressing its appreciation).

3. **## 📝 Operative Clauses**
   Draft 4 highly specific, actionable, and numbered operative clauses. Back each action by strategic arguments or logistics from the Sources. Include sub-clauses (e.g., 1a, 1b) to make them look sophisticated and authentic.

4. **## 💡 Strategic Notes**
   Add a brief, 2-line strategic rationale explaining how these clauses outmaneuver opposing coalitions.

Draft the Clauses briefing now:
"""
        return self.generate(prompt, system_instruction)

    def draft_masterclass(self, query: str, context_chunks: Any, country: str = "the State") -> str:
        """
        Drafts a comprehensive step-by-step basics to advanced masterclass course on the topic for MUN delegates.
        To support generating massive 10-15 page dossiers, this orchestrates the writing chapter-by-chapter.
        """
        # Step 1: Detect the committee style
        sim_style_prompt = f"""
        Analyze the Topic: "{query}" and Represented Role: "{country}".
        Classify the MUN simulation type into one of these formats:
        - Standard UN Meeting / General Assembly (GA / ECOSOC)
        - Joint Crisis Committee (JCC) / Special Agency
        - Historical Roleplay / Historical Crisis
        - Local / Specialized Committee
        
        Respond with ONLY the name of the format (e.g. "Joint Crisis Committee (JCC)"). Do NOT add introductory or explaining text.
        """
        sim_format = "Joint Crisis Committee (JCC)"
        try:
            # We use a short system instruction for fast classification
            res_format = self.generate(sim_style_prompt, "You are a classification assistant. Output only the category.")
            if res_format and len(res_format.strip()) < 100:
                sim_format = res_format.strip().split("\n")[0]
        except Exception:
            pass

        print(f"Detected Simulation Style: {sim_format}")

        modules = ["Foundations", "Timeline", "Stakeholders", "Frameworks", "Precedents", "Strategy", "Rhetoric", "Resolutions"]
        chapters = [
            f"# 🎓 Best Delegate Masterclass Study Dossier: {query}\n"
            f"*Target Simulation Format: {sim_format}*\n"
            f"*Represented Role: {country}*\n\n"
            f"## 📋 Course Overview & Objectives\n"
            f"This dossier provides a comprehensive basics-to-advanced tactical briefing designed to establish "
            f"total domain command in this committee. Grounded in raw crawled research, it outlines strategic framing, "
            f"legal leverage, floor debate clashes, and legislative drafts. Read each module carefully to prepare."
        ]

        for module in modules:
            print(f"Generating Masterclass Chapter: {module}...")
            # Retrieve chunks for this specific module (Decomposed RAG)
            if isinstance(context_chunks, dict):
                module_chunks = context_chunks.get(module, [])
                if not module_chunks:
                    # Fallback to general list if specific dictionary key is empty
                    module_chunks = list(context_chunks.values())[0] if context_chunks else []
            else:
                module_chunks = context_chunks

            chapter_text = self.draft_masterclass_module(query, module, module_chunks, country, sim_format)
            chapters.append(chapter_text)

        return "\n\n---\n\n".join(chapters)

    def draft_masterclass_module(self, query: str, module: str, chunks: List[Dict[str, Any]], country: str, sim_format: str) -> str:
        """Drafts an exhaustive, highly detailed study guide chapter for a single module."""
        system_instruction = (
            "You are an elite academic committee chair and senior crisis director. "
            "Your writing tone is exhaustive, formal, highly structured, and pedagogical. "
            "Draft a massive, comprehensive chapter for the study guide. Write in extensive detail (at least 1500 words for this chapter). "
            "Incorporate exact data, quotes, and legal frameworks from the retrieved sources."
        )

        context_str = ""
        for i, chunk in enumerate(chunks):
            context_str += f"Source [{i+1}] (Trust: {chunk['trust_score']:.2f}, Title: {chunk['title']}, URL: {chunk['url']}):\n{chunk['text']}\n\n"

        prompt = f"""
        Topic of Study: {query}
        Represented Role: {country}
        Simulation Style: {sim_format}
        Target Chapter to write: {module}

        Retrieved Research Context:
        {context_str}

        TASK:
        Write Chapter: {module} of the study guide. 
        It must be extremely detailed, providing deep background, specific historical precedents, and actionable intelligence.
        Aim to write at least 1500 words for this chapter. Use structured markdown. 
        You MUST ground all assertions in the provided sources and include active inline Markdown links in the format [Source Title](Source URL).

        Chapter-Specific Guidelines:
        - **Foundations**: Provide a massive historical and chronological baseline. Explain the history of the issue.
        - **Timeline**: Provide a detailed chronological timeline of key security incidents, disputes, treaty signings, and development milestones with precise dates.
        - **Stakeholders**: Deeply analyze major coalitions, alliances, neutral parties, and our role's specific vulnerabilities and strategic assets.
        - **Frameworks**: Detail international treaties, UN Charter clauses, case precedents, or domestic laws, explaining how to utilize them.
        - **Precedents**: Detail legal and historical precedents (e.g. past ICJ cases, resolution votes, or treaty applications) that can justify our position.
        - **Strategy**: Provide 3 detailed crisis directives (for JCC/Crisis) or standard resolution bloc-building strategies (for GA/ECOSOC).
        - **Rhetoric**: Outline caucus speeches, write 3 Shield defenses and 3 Sword attacks with counter-accusations.
        - **Resolutions**: Provide formal UN operative and preambulatory clauses (for GA) or directives (for JCC), and 3 tactical floor actions.

        Start writing Chapter: {module} now (aim for 1500 words, styled markdown, containing inline [Source Title](Source URL) citations):
        """
        return self.generate(prompt, system_instruction)

