import re
from typing import List, Dict, Set, Tuple, Any, Optional
from backend.database import Database

# Domain-specific Entity Dictionaries
DOMAIN_ENTITIES = {
    "geopolitics": {
        "Country": {
            "China": [r"\bChina\b", r"\bChinese\b", r"\bPRC\b", r"\bPeople's Republic of China\b"],
            "United States": [r"\bUnited States\b", r"\bUSA\b", r"\bU\.S\.\b", r"\bAmerica\b", r"\bAmerican\b"],
            "Taiwan": [r"\bTaiwan\b", r"\bTaiwanese\b", r"\bROC\b", r"\bRepublic of China\b"],
            "Russia": [r"\bRussia\b", r"\bRussian\b", r"\bKremlin\b"],
            "Japan": [r"\bJapan\b", r"\bJapanese\b"],
            "Philippines": [r"\bPhilippines\b", r"\bManila\b", r"\bFilipino\b"],
            "India": [r"\bIndia\b", r"\bIndian\b", r"\bNew Delhi\b"],
            "Vietnam": [r"\bVietnam\b", r"\bVietnamese\b", r"\bHanoi\b"],
            "South Korea": [r"\bSouth Korea\b", r"\bROK\b", r"\bSeoul\b"],
            "North Korea": [r"\bNorth Korea\b", r"\bDPRK\b", r"\bPyongyang\b"],
            "Australia": [r"\bAustralia\b", r"\bAustralian\b", r"\bCanberra\b"],
            "United Kingdom": [r"\bUnited Kingdom\b", r"\bUK\b", r"\bBritain\b", r"\bBritish\b"]
        },
        "Treaty": {
            "UNCLOS": [r"\bUNCLOS\b", r"\bLaw of the Sea\b", r"\bUnited Nations Convention on the Law of the Sea\b"],
            "NATO": [r"\bNATO\b", r"\bNorth Atlantic Treaty\b"],
            "Mutual Defense Treaty": [r"\bMutual Defense Treaty\b", r"\bMDT\b"],
            "Taiwan Relations Act": [r"\bTaiwan Relations Act\b", r"\bTRA\b"],
            "Strategic Ambiguity": [r"\bStrategic Ambiguity\b"],
            "NPT": [r"\bNPT\b", r"\bNon-Proliferation Treaty\b"],
            "Sino-British Joint Declaration": [r"\bSino-British Joint Declaration\b", r"\bJoint Declaration\b"]
        },
        "Military Group": {
            "PLA": [r"\bPLA\b", r"\bPeople's Liberation Army\b", r"\bChinese military\b"],
            "US Navy": [r"\bUS Navy\b", r"\bU\.S\. Navy\b", r"\bSeventh Fleet\b", r"\b7th Fleet\b"],
            "AUKUS": [r"\bAUKUS\b"],
            "QUAD": [r"\bQuadrilateral Security Dialogue\b", r"\bQUAD\b"],
            "Coast Guard": [r"\bCoast Guard\b", r"\bChinese Coast Guard\b", r"\bCCG\b", r"\bUS Coast Guard\b"]
        },
        "Dispute": {
            "South China Sea": [r"\bSouth China Sea\b", r"\bSCS\b"],
            "Taiwan Strait": [r"\bTaiwan Strait\b", r"\bStrait Crisis\b"],
            "Senkaku Islands": [r"\bSenkaku\b", r"\bDiaoyu\b", r"\bSenkaku/Diaoyu Islands\b"],
            "Nine-Dash Line": [r"\bNine-Dash Line\b", r"\bnine dash line\b", r"\bhistorical claims\b"],
            "Scarborough Shoal": [r"\bScarborough\b", r"\bScarborough Shoal\b", r"\bPanatag\b"],
            "Second Thomas Shoal": [r"\bSecond Thomas Shoal\b", r"\bAyungin\b", r"\bSierra Madre\b"],
            "Cyber Warfare": [r"\bcyber retaliation\b", r"\bcyber warfare\b", r"\bcyber attacks\b", r"\bcyber espionage\b", r"\bhacking\b"],
            "Hybrid Warfare": [r"\bhybrid warfare\b", r"\bgrey zone\b", r"\bgray zone\b", r"\bmaritime militia\b"],
            "Semiconductor Geopolitics": [r"\bsemiconductor\b", r"\bchip supply\b", r"\bsemiconductors\b", r"\bexport controls\b", r"\badvanced chips\b"]
        },
        "Company": {
            "TSMC": [r"\bTSMC\b", r"\bTaiwan Semiconductor Manufacturing Company\b"],
            "ASML": [r"\bASML\b"],
            "NVIDIA": [r"\bNVIDIA\b", r"\bNvidia\b"],
            "Huawei": [r"\bHuawei\b"],
            "SMIC": [r"\bSMIC\b", r"\bSemiconductor Manufacturing International Corporation\b"]
        },
        "Region": {
            "Indo-Pacific": [r"\bIndo-Pacific\b", r"\bindopacific\b"],
            "East China Sea": [r"\bEast China Sea\b", r"\bECS\b"],
            "Asia-Pacific": [r"\bAsia-Pacific\b", r"\basiapacific\b"],
            "ASEAN": [r"\bASEAN\b", r"\bAssociation of Southeast Asian Nations\b"]
        }
    },
    "science": {
        "Field of Study": {
            "Quantum Physics": [r"\bquantum physics\b", r"\bquantum mechanics\b", r"\bquantum theory\b"],
            "Artificial Intelligence": [r"\bartificial intelligence\b", r"\bneural network\b", r"\bdeep learning\b", r"\bmachine learning\b", r"\bAI\b"],
            "Genetics": [r"\bgenetics\b", r"\bgenomic\b", r"\bDNA\b", r"\bgenome\b"],
            "Nuclear Physics": [r"\bnuclear physics\b", r"\bfusion energy\b", r"\bnuclear fusion\b"]
        },
        "Tech Concept": {
            "Quantum Computing": [r"\bquantum computing\b", r"\bquantum computer\b", r"\bqutrit\b", r"\bqubit\b"],
            "CRISPR": [r"\bCRISPR\b", r"\bCas9\b", r"\bgene editing\b", r"\bgenome editing\b"],
            "Large Language Model": [r"\blarge language model\b", r"\bLLM\b", r"\btransformers?\b", r"\bgpt\b"]
        },
        "Organization": {
            "NASA": [r"\bNASA\b"],
            "CERN": [r"\bCERN\b"],
            "OpenAI": [r"\bOpenAI\b"],
            "Google DeepMind": [r"\bDeepMind\b", r"\bGoogle DeepMind\b"],
            "MIT": [r"\bMIT\b", r"\bMassachusetts Institute of Technology\b"]
        }
    },
    "history": {
        "Historical Figure": {
            "Julius Caesar": [r"\bJulius Caesar\b", r"\bCaesar\b"],
            "Augustus": [r"\bAugustus\b", r"\bOctavian\b"],
            "Pompey": [r"\bPompey\b", r"\bPompeius\b"],
            "Cicero": [r"\bCicero\b", r"\bMarcus Tullius Cicero\b"],
            "Napoleon": [r"\bNapoleon\b", r"\bBonaparte\b"],
            "Winston Churchill": [r"\bWinston Churchill\b", r"\bChurchill\b"]
        },
        "Event/Period": {
            "Roman Empire": [r"\bRoman Empire\b", r"\bRoman Republic\b"],
            "Julius Caesar Civil War": [r"\bCaesar's Civil War\b", r"\bCrossing the Rubicon\b", r"\bCivil War\b"],
            "French Revolution": [r"\bFrench Revolution\b"],
            "World War I": [r"\bWorld War I\b", r"\bWWI\b", r"\bFirst World War\b"],
            "World War II": [r"\bWorld War II\b", r"\bWWII\b", r"\bSecond World War\b"]
        },
        "Concept/Ism": {
            "Capitalism": [r"\bcapitalism\b", r"\bcapitalist\b"],
            "Socialism": [r"\bsocialism\b", r"\bsocialist\b"],
            "Fascism": [r"\bfascism\b", r"\bfascist\b"],
            "Feudalism": [r"\bfeudalism\b", r"\bfeudal\b"]
        }
    },
    "business": {
        "Company": {
            "Apple": [r"\bApple\b", r"\bApple Inc\b"],
            "Microsoft": [r"\bMicrosoft\b"],
            "Google": [r"\bGoogle\b", r"\bAlphabet\b"],
            "Amazon": [r"\bAmazon\b"],
            "Meta": [r"\bMeta\b", r"\bFacebook\b"],
            "Tesla": [r"\bTesla\b"],
            "NVIDIA": [r"\bNVIDIA\b", r"\bNvidia\b"]
        },
        "Financial Concept": {
            "Inflation": [r"\binflation\b"],
            "Gross Domestic Product": [r"\bGDP\b", r"\bGross Domestic Product\b"],
            "Venture Capital": [r"\bVenture Capital\b", r"\bVC\b"],
            "Initial Public Offering": [r"\bIPO\b", r"\bInitial Public Offering\b"],
            "Merger & Acquisition": [r"\bM&A\b", r"\bmergers and acquisitions\b"]
        }
    },
    "law": {
        "Body": {
            "Supreme Court": [r"\bSupreme Court\b", r"\bSCOTUS\b"],
            "Senate": [r"\bSenate\b"],
            "Congress": [r"\bCongress\b"],
            "Department of Justice": [r"\bDepartment of Justice\b", r"\bDOJ\b"]
        },
        "Legal Concept": {
            "Constitution": [r"\bConstitution\b", r"\bConstitutional\b"],
            "Precedent": [r"\bprecedents?\b", r"\bstare decisis\b"],
            "Habeas Corpus": [r"\bHabeas Corpus\b"],
            "Due Process": [r"\bDue Process\b"]
        }
    }
}

# Retain mapping for main.py imports compatibility
GEOPOLITICAL_ENTITIES = DOMAIN_ENTITIES["geopolitics"]


class EntityExtractor:
    def __init__(self, db: Database):
        self.db = db

    def extract_proper_nouns(self, text: str) -> Set[str]:
        """Extracts capitalized words/phrases that appear multiple times in the text to identify key entities dynamically."""
        pattern = r"\b[A-Z][a-zA-Z0-9\-']+(?:\s+[A-Z][a-zA-Z0-9\-']+)*\b"
        matches = re.findall(pattern, text)
        
        stopwords = {
            "The", "A", "An", "And", "Or", "But", "For", "To", "In", "On", "At", "By", "With", "Of", "About",
            "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
            "January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December",
            "I", "He", "She", "It", "They", "We", "You", "This", "That", "These", "Those", "Source", "Dossier", "Report", "Research"
        }
        
        candidates = set()
        for m in matches:
            m_clean = m.strip()
            if len(m_clean) > 2 and m_clean not in stopwords:
                candidates.add(m_clean)
                
        # Filter for candidates appearing at least twice to avoid singletons/noise
        frequent = set()
        for c in candidates:
            count = len(re.findall(r"\b" + re.escape(c) + r"\b", text))
            if count >= 2:
                frequent.add(c)
                
        return frequent

    def extract_entities_from_text(self, text: str, domain: str = "geopolitics") -> Dict[str, Set[str]]:
        """Scans text for entities using domain-specific dictionaries and proper noun heuristics."""
        found_entities = {}
        domain_lower = domain.lower() if domain else "geopolitics"
        
        # 1. Match against domain-specific dictionary
        entities_dict = DOMAIN_ENTITIES.get(domain_lower, DOMAIN_ENTITIES["geopolitics"])
        for category, entities in entities_dict.items():
            found_entities[category] = set()
            for entity_name, patterns in entities.items():
                for pattern in patterns:
                    if re.search(pattern, text, re.IGNORECASE):
                        found_entities[category].add(entity_name)
                        break
                        
        # 2. Run Heuristic Proper Noun Extractor as dynamic fallbacks
        proper_nouns = self.extract_proper_nouns(text)
        
        # Determine fallback category label based on domain
        fallback_cat = "Key Entity"
        if domain_lower == "science":
            fallback_cat = "Scientific Term"
        elif domain_lower == "history":
            fallback_cat = "Historical Figure/Event"
        elif domain_lower == "business":
            fallback_cat = "Company/Market Asset"
        elif domain_lower == "law":
            fallback_cat = "Legal Figure/Term"
            
        if fallback_cat not in found_entities:
            found_entities[fallback_cat] = set()
            
        # Add proper nouns that haven't been captured by the dictionary yet
        existing_names = set()
        for names in found_entities.values():
            existing_names.update(names)
            
        for pn in proper_nouns:
            is_new = True
            pn_lower = pn.lower()
            for existing in existing_names:
                if pn_lower in existing.lower() or existing.lower() in pn_lower:
                    is_new = False
                    break
            if is_new:
                found_entities[fallback_cat].add(pn)
                
        # Clean empty lists
        return {cat: names for cat, names in found_entities.items() if names}

    def process_source_entities(self, source_id: int):
        """Processes a single source article, extracts entities and co-occurrences, inserts to DB."""
        source = self.db.get_source(source_id)
        if not source:
            return

        raw_content = source["raw_content"]
        domain = source.get("category", "geopolitics") # category column maps to the domain

        # 1. Extract source-wide entities and insert them into DB
        source_entities = self.extract_entities_from_text(raw_content, domain)
        flat_entities = [] # list of (name, type)
        for category, names in source_entities.items():
            for name in names:
                self.db.insert_entity(name, category)
                flat_entities.append((name, category))

        # 2. Extract co-occurrences within paragraphs/chunks to build edges
        paragraphs = raw_content.split("\n\n")
        
        for p in paragraphs:
            if len(p.strip()) < 100:
                continue
            
            p_entities = self.extract_entities_from_text(p, domain)
            
            # Gather all detected entity names in this paragraph
            all_detected = []
            for category, names in p_entities.items():
                all_detected.extend(names)
                
            # If 2 or more entities are found, build connections
            if len(all_detected) >= 2:
                for i in range(len(all_detected)):
                    for j in range(i + 1, len(all_detected)):
                        entity_1 = all_detected[i]
                        entity_2 = all_detected[j]
                        
                        description = self._find_context_sentence(p, entity_1, entity_2, domain)
                        if not description:
                            description = f"Co-occurrence of {entity_1} and {entity_2} in research context."
                            
                        self.db.insert_relation(entity_1, entity_2, source_id, description)

    def _find_context_sentence(self, paragraph: str, entity_1: str, entity_2: str, domain: str) -> Optional[str]:
        """Finds a sentence inside a paragraph that contains both entities."""
        sentences = re.split(r"(?<=[.!?])\s+", paragraph)
        domain_lower = domain.lower() if domain else "geopolitics"
        
        # Helper to check if a sentence matches any patterns for the entity
        def entity_in_sentence(sentence: str, entity_name: str) -> bool:
            if entity_name.lower() in sentence.lower():
                return True
                
            entities_dict = DOMAIN_ENTITIES.get(domain_lower, DOMAIN_ENTITIES["geopolitics"])
            for category, entities in entities_dict.items():
                if entity_name in entities:
                    for pattern in entities[entity_name]:
                        if re.search(pattern, sentence, re.IGNORECASE):
                            return True
            return False

        for sentence in sentences:
            if entity_in_sentence(sentence, entity_1) and entity_in_sentence(sentence, entity_2):
                cleaned = sentence.strip()
                if len(cleaned) > 250:
                    cleaned = cleaned[:247] + "..."
                return cleaned
        return None

    def process_all_sources(self):
        """Runs entity extraction across all sources currently in the database."""
        sources = self.db.list_sources()
        for src in sources:
            self.process_source_entities(src["id"])
