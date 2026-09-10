"""
Language detection utilities for enforcing English/Kiswahili policy.
"""
import re
import structlog
from typing import Optional


def detect_language(text: str) -> Optional[str]:
    """
    Detect if text is in English, Kiswahili, or another language.
    
    Returns: 'english', 'kiswahili', 'mixed', or 'other'
    """
    if not text or not text.strip():
        return None
    
    # Simple heuristic based on common words/phrases
    kiswahili_words = [
        'asante', 'habari', 'jambo', 'sawa', 'ndio', 'hapana', 'tafadhali',
        'ninaweza', 'unaweza', 'tunaweza', 'nataka', 'nitataka', 'sita',
        'fanya', 'weka', 'chukua', 'pata', 'nenda', 'kuja', 'rudi',
        'sikiliza', 'elewa', 'andika', 'jibu', 'saidia', 'msaada',
        'shida', 'tatizo', 'njia', 'fungua', 'badilika', 'abadilika',
        'endelea', 'anza', 'subiri', 'fuatilia', 'sahau',
        'wakati', 'muda', 'kubwa', 'ukubwa', 'wingi', 'wote', 'kuandika',
        'jibu', 'majibu', 'sauti', 'kwa', 'kati', 'ya', 'wa', 'za', 'zaidi',
        'bado', 'mbaya', 'pamoja', 'shikamoo', 'mpoke', 'shule',
        'chakula', 'kula', 'kunywa', 'nyama', 'samaki', 'jiko',
        'nyumba', 'mji', 'mitaa', 'nguo', 'chuma', 'saa', 'jioni',
        'usiku', 'alasiri', 'kuchelea', 'baiskeli', 'bei', 'kauza',
        'punguza', 'shughuli', 'kazi', 'afya', 'hospitali', 'daktari',
        'dawa', 'madawa', 'kliniki', 'mkopo', 'matumizi', 'matibabu',
        'kutumia', 'tiba', 'upata', 'afya', 'salama', 'amani', 'mama',
        'baba', 'mtoto', 'kijana', 'mwana', 'binti', 'kijiji', 'serikali',
        'gaa', 'kugwa', 'nchi', 'uchumi', 'mwamba', 'fundi', 'ufundi',
        'mfanyakazi'
    ]
    
    english_words = [
        'the', 'is', 'are', 'was', 'were', 'be', 'been', 'being', 'have', 'has', 'had',
        'do', 'does', 'did', 'will', 'would', 'could', 'should', 'may', 'might',
        'can', 'shall', 'must', 'ought', 'need', 'dare', 'want', 'like', 'love',
        'hope', 'wish', 'try', 'make', 'get', 'give', 'take', 'come', 'go', 'see',
        'know', 'think', 'feel', 'believe', 'understand', 'remember', 'forget',
        'use', 'work', 'play', 'live', 'stay', 'move', 'walk', 'run', 'jump', 'sit',
        'stand', 'lie', 'sleep', 'wake', 'eat', 'drink', 'speak', 'talk', 'say',
        'tell', 'ask', 'answer', 'help', 'support', 'assist', 'serve', 'lead',
        'follow', 'guide', 'teach', 'learn', 'study', 'read', 'write', 'listen',
        'hear', 'watch', 'look', 'find', 'search', 'seek', 'discover', 'create',
        'build', 'develop', 'grow', 'change', 'improve', 'fix', 'solve',
        'handle', 'manage', 'control', 'direct', 'organize', 'plan', 'design',
        'start', 'begin', 'end', 'finish', 'complete', 'continue', 'stop', 'pause',
        'wait', 'stay', 'remain', 'keep', 'hold', 'carry', 'bring', 'send',
        'receive', 'offer', 'provide', 'supply', 'deliver', 'produce', 'generate',
        'establish', 'found', 'invent', 'locate', 'identify', 'recognize', 'realize',
        'comprehend', 'grasp', 'research', 'investigate', 'examine', 'analyze',
        'evaluate', 'assess', 'judge', 'determine', 'decide', 'choose', 'select',
        'pick', 'prefer', 'enjoy', 'hate', 'dislike', 'need', 'require', 'desire',
        'anticipate', 'consider', 'regard', 'view', 'observe', 'notice', 'perceive',
        'sense', 'experience', 'undergo', 'encounter', 'face', 'meet', 'confront',
        'deal', 'tackle', 'address', 'approach', 'attack', 'assault', 'defend',
        'protect', 'guard', 'save', 'rescue', 'aid', 'operate', 'function',
        'perform', 'execute', 'conduct', 'administer', 'govern', 'rule', 'steer',
        'pilot', 'drive', 'ride', 'travel', 'proceed', 'advance', 'progress',
        'succeed', 'fail', 'error', 'mistake', 'fault', 'blame', 'guilt', 'shame',
        'regret', 'sorry', 'apologize', 'forgive', 'excuse', 'pardon', 'thank',
        'appreciate', 'welcome', 'greet', 'introduce', 'present', 'show', 'display',
        'demonstrate', 'illustrate', 'explain', 'describe', 'discuss', 'debate',
        'argue', 'convince', 'persuade', 'influence', 'affect', 'impact', 'effect',
        'alter', 'modify', 'adjust', 'adapt', 'adopt', 'accept', 'reject', 'refuse',
        'deny', 'admit', 'confess', 'acknowledge', 'inform', 'notify', 'alert',
        'warn', 'advise', 'recommend', 'suggest', 'propose', 'grant', 'allow',
        'permit', 'enable', 'empower', 'authorize', 'approve', 'back', 'endorse',
        'sponsor', 'fund', 'finance', 'pay', 'spend', 'cost', 'price', 'value',
        'worth', 'charge', 'fee', 'bill', 'invoice', 'receipt', 'account',
        'balance', 'credit', 'debt', 'loan', 'mortgage', 'insurance', 'policy',
        'contract', 'agreement', 'deal', 'treaty', 'pact', 'alliance', 'partnership',
        'relationship', 'connection', 'link', 'tie', 'bond', 'association',
        'organization', 'group', 'team', 'club', 'society', 'community', 'public',
        'people', 'population', 'nation', 'country', 'state', 'region', 'area',
        'place', 'location', 'site', 'position', 'situation', 'condition', 'status',
        'case', 'matter', 'issue', 'problem', 'question', 'topic', 'subject',
        'theme', 'point', 'idea', 'concept', 'notion', 'thought', 'belief',
        'opinion', 'view', 'perspective', 'standpoint', 'attitude', 'approach',
        'method', 'technique', 'strategy', 'tactic', 'plan', 'scheme', 'program',
        'project', 'initiative', 'campaign', 'mission', 'goal', 'objective',
        'target', 'aim', 'purpose', 'function', 'role', 'job', 'work', 'task',
        'duty', 'responsibility', 'obligation', 'assignment', 'challenge',
        'opportunity', 'chance', 'luck', 'fortune', 'destiny', 'fate', 'possibility',
        'potential', 'capacity', 'ability', 'skill', 'talent', 'gift', 'strength',
        'weakness', 'limit', 'limitation', 'constraint', 'restriction', 'requirement',
        'criterion', 'standard', 'rule', 'law', 'regulation', 'guideline', 'principle',
        'value', 'conviction', 'faith', 'trust', 'confidence', 'doubt', 'uncertainty',
        'certainty', 'assurance', 'guarantee', 'promise', 'commitment', 'dedication',
        'loyalty', 'fidelity', 'faithfulness', 'honesty', 'integrity', 'truth',
        'truthfulness', 'sincerity', 'genuineness', 'authenticity', 'originality',
        'creativity', 'innovation', 'invention', 'discovery', 'exploration',
        'research', 'study', 'analysis', 'examination', 'evaluation', 'assessment',
        'review', 'critique', 'criticism', 'feedback', 'response', 'reaction',
        'reply', 'answer', 'solution', 'resolution', 'result', 'outcome', 'consequence',
        'power', 'authority', 'control', 'dominance', 'supremacy', 'command', 'order',
        'instruction', 'direction', 'guidance', 'leadership', 'management',
        'administration', 'governance', 'government', 'politics', 'democracy',
        'freedom', 'liberty', 'rights', 'justice', 'order', 'peace', 'security',
        'safety', 'protection', 'defense', 'shelter', 'refuge', 'asylum', 'sanctuary',
        'home', 'house', 'building', 'structure', 'space', 'room', 'territory',
        'land', 'world', 'earth', 'planet', 'universe', 'cosmos', 'existence',
        'life', 'death', 'birth', 'growth', 'development', 'evolution', 'change',
        'transformation', 'metamorphosis', 'adaptation', 'modification', 'alteration',
        'revision', 'correction', 'enhancement', 'upgrade', 'update', 'progress',
        'advancement', 'expansion', 'extension', 'increase', 'decrease', 'reduction',
        'decline', 'fall', 'drop', 'rise', 'climb', 'ascend', 'descend', 'crash',
        'collapse', 'failure', 'success', 'victory', 'triumph', 'achievement',
        'accomplishment', 'fulfillment', 'realization', 'actualization', 'manifestation',
        'exhibition', 'performance', 'execution', 'implementation', 'application',
        'usage', 'utilization', 'operation', 'functioning', 'activity', 'action',
        'deed', 'act', 'behavior', 'conduct', 'practice', 'habit', 'routine',
        'custom', 'tradition', 'convention', 'standard', 'norm', 'statute', 'ordinance',
        'decree', 'mandate', 'directive', 'recommendation', 'suggestion', 'advice',
        'counsel', 'tip', 'hint', 'clue', 'sign', 'indication', 'signal', 'message',
        'communication', 'conversation', 'dialogue', 'discussion', 'talk', 'speech',
        'address', 'lecture', 'presentation', 'explanation', 'description', 'account',
        'report', 'story', 'narrative', 'tale', 'history', 'record', 'chronicle',
        'log', 'journal', 'diary', 'memo', 'note', 'letter', 'email', 'correspondence'
    ]
    
    text_lower = text.lower()
    words = re.findall(r'\b\w+\b', text_lower)
    
    if not words:
        return None
    
    kiswahili_count = sum(1 for word in words if word in kiswahili_words)
    english_count = sum(1 for word in words if word in english_words)
    
    if kiswahili_count > 0 and english_count > 0:
        return 'mixed'
    elif kiswahili_count > 0:
        return 'kiswahili'
    elif english_count > 0:
        return 'english'
    else:
        return 'other'


def is_allowed_language(text: str) -> bool:
    """
    Check if text is in allowed languages (English or Kiswahili or mixed).
    
    Returns True if text is English, Kiswahili, or mixed; False otherwise.
    """
    detected = detect_language(text)
    return detected in ['english', 'kiswahili', 'mixed', None]


def get_language_fallback() -> str:
    """
    Return a fallback response when language policy is violated.
    """
    return "I apologize, but I currently only support English and Kiswahili. Please write your question in English or Kiswahili, and I'll be happy to help you."


def enforce_language_policy(response_text: str, original_message: str = "") -> str:
    """
    Enforce language policy on AI response.
    
    If the response is not in English or Kiswahili, return a fallback message.
    This is a lightweight post-generation safety net.
    
    Args:
        response_text: The AI-generated response to check
        original_message: The original user message (for context if needed)
    
    Returns:
        The original response if in allowed language, otherwise a fallback message
    """
    if not response_text or not response_text.strip():
        return response_text
    
    if is_allowed_language(response_text):
        return response_text
    
    # Language policy violated - return fallback
    logger = structlog.get_logger(__name__)
    logger.warning(
        "Language policy violation detected",
        detected_language=detect_language(response_text),
        response_length=len(response_text),
    )
    
    return get_language_fallback()
