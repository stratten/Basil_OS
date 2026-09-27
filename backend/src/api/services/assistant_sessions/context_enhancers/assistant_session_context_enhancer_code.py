import re
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class AssistantSessionCodeEnhancer:
    """
    Specialized context enhancer for code editor AssistantSession suggestions.
    Handles programming languages, debugging, documentation, version control, and code review contexts.
    """
    
    def __init__(self, coordinator=None):
        self.coordinator = coordinator  # Reference to AssistantSessionContextEnhancer for shared methods
        # Code editor detection patterns
        self.code_indicators = [
            r"^\s*(?:class|def|function|var|let|const|func|struct|enum|interface)\s+",
            r"^\s*(?:import|#include|from\s+\w+\s+import|using\s+namespace)\s+",
            r"^\s*(?://|/\*|\*|#|\"\"\"|\'\'\').*",
            r"{\s*$|}\s*$",
            r"Line \d+(?::\d+)?",
            r"(?:Syntax|Parse|Compile|Runtime)\s+Error",
            r"\.(?:swift|py|js|ts|java|cpp|c|h|m|mm|rb|go|rs|kt|scala|php|cs)\b",
            r"(?:GitHub|GitLab|Bitbucket)",
            r"(?:Pull Request|Merge Request|PR|MR)\s*#?\d*",
            r"(?:Stack Trace|Traceback|Backtrace)",
            r"(?:git\s+(?:add|commit|push|pull|merge|branch|checkout|status))",
            r"(?:npm|pip|yarn|cargo|gradle|maven)\s+(?:install|build|run|test)",
        ]
        
        # Programming language patterns
        self.language_indicators = {
            "swift": [
                r"\bfunc\s+\w+\(", r"\bvar\s+\w+:", r"\blet\s+\w+\s*=", r"\bclass\s+\w+:",
                r"\bstruct\s+\w+\s*{", r"\benum\s+\w+\s*{", r"\bprotocol\s+\w+\s*{",
                r"\b(?:@\w+|override|private|public|internal|fileprivate)\b",
                r"\bguard\s+let\b", r"\bif\s+let\b", r"\bswitch\s+\w+\s*{",
                r"\.swift\b", r"import\s+(?:Foundation|UIKit|SwiftUI|Combine)"
            ],
            "python": [
                r"\bdef\s+\w+\(", r"\bclass\s+\w+\(", r"\bimport\s+\w+", r"\bfrom\s+\w+\s+import",
                r"^\s*#.*", r"\"\"\".*\"\"\"", r"\'\'\'.*\'\'\'", r"\bif\s+__name__\s*==\s*['\"]__main__['\"]",
                r"\.py\b", r"\b(?:print|range|len|str|int|float|list|dict|tuple)\(",
                r"\bfor\s+\w+\s+in\s+", r"\bwith\s+open\(", r"\btry:\s*$", r"\bexcept\s+\w*:"
            ],
            "javascript": [
                r"\bfunction\s+\w*\(", r"\bconst\s+\w+\s*=", r"\blet\s+\w+\s*=", r"\bvar\s+\w+\s*=",
                r"\.js\b|\.ts\b", r"\bconsole\.log\(", r"\brequire\(", r"\bimport\s+.*\bfrom\b",
                r"\bexport\s+(?:default\s+)?", r"=>\s*{?", r"\basync\s+function", r"\bawait\s+",
                r"\b(?:React|useState|useEffect|Component)\b", r"\.(?:map|filter|reduce|forEach)\("
            ],
            "java": [
                r"\bpublic\s+(?:static\s+)?(?:void|int|String|boolean)\s+\w+\(", r"\bclass\s+\w+\s*{",
                r"\bpublic\s+class\s+\w+", r"\bprivate\s+\w+\s+\w+", r"\bimport\s+[\w.]+;",
                r"\.java\b", r"\bSystem\.out\.println\(", r"\bnew\s+\w+\(", r"\bthis\.",
                r"\b(?:public|private|protected|static|final|abstract)\b", r"\bextends\s+\w+",
                r"\btry\s*{", r"\bcatch\s*\(\w+\s+\w+\)\s*{"
            ],
            "cpp": [
                r"#include\s*<\w+>", r"\bint\s+main\(", r"\bclass\s+\w+\s*{", r"\bstruct\s+\w+\s*{",
                r"\.(?:cpp|cc|cxx|c|h|hpp)\b", r"\bstd::", r"\bcout\s*<<", r"\bcin\s*>>",
                r"\bnamespace\s+\w+", r"\busing\s+namespace\s+std;", r"\btemplate\s*<",
                r"\bpublic:|private:|protected:", r"\bvirtual\s+", r"\bconst\s+\w+\s*&"
            ]
        }
        
        # Code context patterns
        self.debugging_indicators = [
            r"(?:Syntax|Parse|Compile|Runtime|Logic|Null Pointer|Segmentation)\s+(?:Error|Exception)",
            r"Stack Trace|Traceback|Backtrace|Call Stack",
            r"Exception\s+in\s+thread", r"Error\s+at\s+line\s+\d+",
            r"Assertion\s+failed", r"Breakpoint\s+\d+", r"Debug\s+console",
            r"Unhandled\s+exception", r"Memory\s+leak", r"Access\s+violation"
        ]
        
        self.documentation_indicators = [
            r"README\.md|CHANGELOG\.md|API\.md|CONTRIBUTING\.md",
            r"\/\*\*.*\*\/", r"\"\"\".*\"\"\"", r"\'\'\'.*\'\'\'",
            r"@param|@return|@throws|@deprecated|@since|@author",
            r"#\s*TODO|#\s*FIXME|#\s*NOTE|#\s*BUG|#\s*HACK",
            r"Documentation|API\s+Reference|Usage\s+Example",
            r"Getting\s+Started|Installation|Configuration"
        ]
        
        self.version_control_indicators = [
            r"git\s+(?:add|commit|push|pull|merge|branch|checkout|status|log|diff)",
            r"Pull\s+Request|Merge\s+Request|PR\s*#?\d*|MR\s*#?\d*",
            r"Commit\s+message|Commit\s+hash|SHA|branch\s+\w+",
            r"Merge\s+conflict|Conflict\s+in\s+file",
            r"GitHub|GitLab|Bitbucket|Source\s+control",
            r"Code\s+review|Review\s+comments|Approved|Changes\s+requested"
        ]

    def enhance(self, content: str, instruction: str, personalization_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Enhance code editor-specific AssistantSession suggestions with personalization support.
        
        Args:
            content: Raw OCR text from code editor interface
            instruction: User's voice instruction
            
        Returns:
            Enhancement result with code-specific processing
        """
        try:
            # Detect specific code context type
            code_context = self._detect_code_context(content)
            
            if code_context == "debugging":
                return self._enhance_debugging_context(content, instruction)
            elif code_context == "documentation":
                return self._enhance_documentation_context(content, instruction)
            elif code_context == "version_control":
                return self._enhance_version_control_context(content, instruction)
            else:
                # Detect programming language and provide language-specific assistance
                language = self._detect_programming_language(content)
                return self._enhance_language_specific_context(content, instruction, language)
                
        except Exception as e:
            logger.error(f"Error in code enhancement: {e}")
            return {
                "context_type": "code_generic",
                "filtered_content": content,
                "enhanced_prompt": self._build_fallback_prompt(content, instruction),
                "metadata": {"error": str(e), "enhancer": "code"}
            }

    def _detect_code_context(self, content: str) -> str:
        """Detect specific code context type from content."""
        if any(re.search(pattern, content, re.IGNORECASE | re.MULTILINE) 
               for pattern in self.debugging_indicators):
            return "debugging"
        elif any(re.search(pattern, content, re.IGNORECASE | re.MULTILINE) 
                 for pattern in self.documentation_indicators):
            return "documentation"
        elif any(re.search(pattern, content, re.IGNORECASE | re.MULTILINE) 
                 for pattern in self.version_control_indicators):
            return "version_control"
        else:
            return "coding"

    def _detect_programming_language(self, content: str) -> str:
        """Detect programming language from content patterns."""
        language_scores = {}
        
        for language, patterns in self.language_indicators.items():
            score = sum(1 for pattern in patterns 
                       if re.search(pattern, content, re.IGNORECASE | re.MULTILINE))
            if score > 0:
                language_scores[language] = score
        
        if language_scores:
            # Return language with highest score
            return max(language_scores, key=language_scores.get)
        else:
            return "generic"

    def _enhance_debugging_context(self, content: str, instruction: str) -> Dict[str, Any]:
        """Handle debugging-specific enhancement."""
        metadata = self._extract_debugging_metadata(content)
        metadata["enhancer"] = "code"
        metadata["code_context"] = "debugging"
        
        enhanced_prompt = self._build_debugging_prompt(content, instruction, metadata)
        
        return {
            "context_type": "code_debugging",
            "filtered_content": content,
            "enhanced_prompt": enhanced_prompt,
            "metadata": metadata
        }

    def _enhance_documentation_context(self, content: str, instruction: str) -> Dict[str, Any]:
        """Handle documentation-specific enhancement."""
        metadata = self._extract_documentation_metadata(content)
        metadata["enhancer"] = "code"
        metadata["code_context"] = "documentation"
        
        enhanced_prompt = self._build_documentation_prompt(content, instruction, metadata)
        
        return {
            "context_type": "code_documentation",
            "filtered_content": content,
            "enhanced_prompt": enhanced_prompt,
            "metadata": metadata
        }

    def _enhance_version_control_context(self, content: str, instruction: str) -> Dict[str, Any]:
        """Handle version control-specific enhancement."""
        metadata = self._extract_version_control_metadata(content)
        metadata["enhancer"] = "code"
        metadata["code_context"] = "version_control"
        
        enhanced_prompt = self._build_version_control_prompt(content, instruction, metadata)
        
        return {
            "context_type": "code_version_control",
            "filtered_content": content,
            "enhanced_prompt": enhanced_prompt,
            "metadata": metadata
        }

    def _enhance_language_specific_context(self, content: str, instruction: str, language: str) -> Dict[str, Any]:
        """Handle language-specific code enhancement."""
        metadata = self._extract_language_metadata(content, language)
        metadata["enhancer"] = "code"
        metadata["code_context"] = "coding"
        metadata["detected_language"] = language
        
        enhanced_prompt = self._build_language_specific_prompt(content, instruction, language, metadata)
        
        return {
            "context_type": f"code_{language}",
            "filtered_content": content,
            "enhanced_prompt": enhanced_prompt,
            "metadata": metadata
        }

    def _extract_debugging_metadata(self, content: str) -> Dict[str, Any]:
        """Extract debugging-specific metadata."""
        metadata = {}
        
        # Check for error types
        error_types = []
        error_patterns = [
            (r"Syntax\s+Error", "syntax"),
            (r"Runtime\s+Error", "runtime"),
            (r"Null\s+Pointer", "null_pointer"),
            (r"Segmentation\s+Fault", "segmentation_fault"),
            (r"Memory\s+Leak", "memory_leak"),
            (r"Assertion\s+Failed", "assertion")
        ]
        
        for pattern, error_type in error_patterns:
            if re.search(pattern, content, re.IGNORECASE):
                error_types.append(error_type)
        
        if error_types:
            metadata["error_types"] = error_types
        
        # Check for line numbers
        line_numbers = re.findall(r"line\s+(\d+)", content, re.IGNORECASE)
        if line_numbers:
            metadata["error_lines"] = [int(line) for line in line_numbers]
        
        # Check for stack trace
        if re.search(r"Stack\s+Trace|Traceback", content, re.IGNORECASE):
            metadata["has_stack_trace"] = True
        
        return metadata

    def _extract_documentation_metadata(self, content: str) -> Dict[str, Any]:
        """Extract documentation-specific metadata."""
        metadata = {}
        
        # Check for documentation type
        if re.search(r"README\.md", content, re.IGNORECASE):
            metadata["doc_type"] = "readme"
        elif re.search(r"API\.md|API\s+Reference", content, re.IGNORECASE):
            metadata["doc_type"] = "api"
        elif re.search(r"\/\*\*.*\*\/|\"\"\".*\"\"\"|\'\'\'.*\'\'\'", content, re.MULTILINE | re.DOTALL):
            metadata["doc_type"] = "inline"
        
        # Check for documentation tags
        doc_tags = re.findall(r"@(\w+)", content)
        if doc_tags:
            metadata["doc_tags"] = list(set(doc_tags))
        
        # Check for code examples
        code_examples = re.findall(r"```[\w]*\n.*?\n```", content, re.MULTILINE | re.DOTALL)
        if code_examples:
            metadata["has_code_examples"] = True
            metadata["code_example_count"] = len(code_examples)
        
        return metadata

    def _extract_version_control_metadata(self, content: str) -> Dict[str, Any]:
        """Extract version control-specific metadata."""
        metadata = {}
        
        # Check for git operations
        git_operations = []
        git_patterns = [
            (r"git\s+add", "add"),
            (r"git\s+commit", "commit"),
            (r"git\s+push", "push"),
            (r"git\s+pull", "pull"),
            (r"git\s+merge", "merge"),
            (r"git\s+branch", "branch")
        ]
        
        for pattern, operation in git_patterns:
            if re.search(pattern, content, re.IGNORECASE):
                git_operations.append(operation)
        
        if git_operations:
            metadata["git_operations"] = git_operations
        
        # Check for PR/MR context
        pr_match = re.search(r"(?:PR|Pull\s+Request)\s*#?(\d+)", content, re.IGNORECASE)
        if pr_match:
            metadata["pr_number"] = pr_match.group(1)
        
        # Check for merge conflicts
        if re.search(r"Merge\s+conflict|Conflict\s+in\s+file", content, re.IGNORECASE):
            metadata["has_merge_conflict"] = True
        
        return metadata

    def _extract_language_metadata(self, content: str, language: str) -> Dict[str, Any]:
        """Extract language-specific metadata."""
        metadata = {"language": language}
        
        # Extract imports/includes
        import_patterns = {
            "swift": r"import\s+([\w.]+)",
            "python": r"(?:import\s+([\w.]+)|from\s+([\w.]+)\s+import)",
            "javascript": r"(?:import\s+.*\s+from\s+['\"]([^'\"]+)['\"]|require\(['\"]([^'\"]+)['\"]\))",
            "java": r"import\s+([\w.]+);",
            "cpp": r"#include\s*[<\"]([^>\"]+)[>\"]"
        }
        
        if language in import_patterns:
            imports = re.findall(import_patterns[language], content, re.IGNORECASE)
            if imports:
                # Flatten tuples from group matches
                imports = [item for sublist in imports for item in (sublist if isinstance(sublist, tuple) else [sublist]) if item]
                metadata["imports"] = list(set(imports))
        
        # Extract function/method definitions
        function_patterns = {
            "swift": r"func\s+(\w+)\(",
            "python": r"def\s+(\w+)\(",
            "javascript": r"function\s+(\w+)\(|(\w+)\s*=\s*\(",
            "java": r"(?:public|private|protected)?\s*(?:static\s+)?[\w<>]+\s+(\w+)\(",
            "cpp": r"[\w<>:]+\s+(\w+)\("
        }
        
        if language in function_patterns:
            functions = re.findall(function_patterns[language], content, re.IGNORECASE)
            if functions:
                # Flatten tuples and filter empty strings
                functions = [item for sublist in functions for item in (sublist if isinstance(sublist, tuple) else [sublist]) if item]
                metadata["functions"] = list(set(functions))
        
        return metadata

    def _build_debugging_prompt(self, content: str, instruction: str, metadata: Dict[str, Any]) -> str:
        """Build debugging-specific prompt."""
        error_info = ""
        if "error_types" in metadata:
            error_info = f"\n- Error types detected: {', '.join(metadata['error_types'])}"
        
        line_info = ""
        if "error_lines" in metadata:
            line_info = f"\n- Error lines: {', '.join(map(str, metadata['error_lines']))}"
        
        stack_info = ""
        if metadata.get("has_stack_trace", False):
            stack_info = "\n- Stack trace present - focus on call hierarchy and error propagation"
        
        return f"""You are an AI assistant helping with debugging code.

DEBUGGING INSTRUCTIONS:
- Analyze the error carefully and provide specific, actionable solutions
- Focus on the root cause rather than just the symptoms{error_info}{line_info}{stack_info}
- Suggest debugging strategies and tools when appropriate
- Provide code fixes with clear explanations
- Consider edge cases and potential side effects

CURRENT DEBUGGING CONTEXT:
{content}

USER INSTRUCTION: {instruction}

Provide debugging assistance that helps identify and solve the problem:"""

    def _build_documentation_prompt(self, content: str, instruction: str, metadata: Dict[str, Any]) -> str:
        """Build documentation-specific prompt."""
        doc_type_info = ""
        if "doc_type" in metadata:
            doc_type_info = f"\n- Documentation type: {metadata['doc_type']}"
        
        tags_info = ""
        if "doc_tags" in metadata:
            tags_info = f"\n- Documentation tags: {', '.join(metadata['doc_tags'])}"
        
        examples_info = ""
        if metadata.get("has_code_examples", False):
            examples_info = f"\n- Contains {metadata.get('code_example_count', 0)} code examples"
        
        return f"""You are an AI assistant helping with code documentation.

DOCUMENTATION INSTRUCTIONS:
- Write clear, comprehensive documentation that helps other developers
- Include practical examples and use cases{doc_type_info}{tags_info}{examples_info}
- Use proper documentation formatting and conventions
- Explain complex concepts in accessible language
- Include parameter descriptions, return values, and exceptions where relevant

CURRENT DOCUMENTATION CONTEXT:
{content}

USER INSTRUCTION: {instruction}

Generate well-structured documentation that enhances developer understanding:"""

    def _build_version_control_prompt(self, content: str, instruction: str, metadata: Dict[str, Any]) -> str:
        """Build version control-specific prompt."""
        git_info = ""
        if "git_operations" in metadata:
            git_info = f"\n- Git operations: {', '.join(metadata['git_operations'])}"
        
        pr_info = ""
        if "pr_number" in metadata:
            pr_info = f"\n- Pull Request #: {metadata['pr_number']}"
        
        conflict_info = ""
        if metadata.get("has_merge_conflict", False):
            conflict_info = "\n- Merge conflict detected - focus on resolution strategies"
        
        return f"""You are an AI assistant helping with version control and code collaboration.

VERSION CONTROL INSTRUCTIONS:
- Provide clear, professional communication for code reviews and commits
- Follow conventional commit message formats when appropriate{git_info}{pr_info}{conflict_info}
- Focus on explaining changes and their impact
- Suggest best practices for collaboration and code organization
- Help resolve conflicts with minimal disruption to codebase

CURRENT VERSION CONTROL CONTEXT:
{content}

USER INSTRUCTION: {instruction}

Generate version control content that promotes good collaboration practices:"""

    def _build_language_specific_prompt(self, content: str, instruction: str, language: str, metadata: Dict[str, Any]) -> str:
        """Build language-specific coding prompt."""
        language_info = f"\n- Programming language: {language.title()}"
        
        imports_info = ""
        if "imports" in metadata and metadata["imports"]:
            imports_info = f"\n- Detected imports: {', '.join(metadata['imports'][:5])}{'...' if len(metadata['imports']) > 5 else ''}"
        
        functions_info = ""
        if "functions" in metadata and metadata["functions"]:
            functions_info = f"\n- Detected functions: {', '.join(metadata['functions'][:5])}{'...' if len(metadata['functions']) > 5 else ''}"
        
        language_specific_guidance = {
            "swift": "- Follow Swift naming conventions and use optionals safely\n- Leverage SwiftUI and Combine patterns when appropriate",
            "python": "- Follow PEP 8 style guidelines and use Pythonic idioms\n- Consider type hints and proper error handling",
            "javascript": "- Use modern ES6+ features and async/await patterns\n- Follow JavaScript best practices and consider TypeScript",
            "java": "- Follow Java naming conventions and use appropriate design patterns\n- Consider object-oriented principles and exception handling",
            "cpp": "- Follow C++ best practices and consider memory management\n- Use modern C++ features and RAII principles"
        }
        
        specific_guidance = language_specific_guidance.get(language, "- Follow language-specific best practices and conventions")
        
        return f"""You are an AI assistant helping with {language.title()} programming.

{language.upper()} PROGRAMMING INSTRUCTIONS:
- Write clean, readable, and maintainable code{language_info}{imports_info}{functions_info}
- {specific_guidance}
- Provide explanations for complex logic and algorithms
- Suggest improvements for performance and code quality
- Include proper error handling and edge case considerations

CURRENT {language.upper()} CODE CONTEXT:
{content}

USER INSTRUCTION: {instruction}

Generate {language.title()} code or assistance that follows best practices and conventions:"""

    def _build_fallback_prompt(self, content: str, instruction: str) -> str:
        """Build fallback prompt when enhancement fails."""
        return f"""You are an AI assistant helping with a coding task.

CONTENT:
{content}

USER INSTRUCTION: {instruction}

Response:""" 