from __future__ import annotations


def _starter(name: str, params: str, py_params: str, java_signature: str, csharp_signature: str) -> dict[str, str]:
    return {
        "typescript": (
            f"export function {name}({params}): unknown {{\n"
            "  // Explain your thinking as you code.\n"
            "  return null\n"
            "}\n"
        ),
        "javascript": (
            f"export function {name}({params} ) {{\n"
            "  // Explain your thinking as you code.\n"
            "  return null\n"
            "}\n"
        ),
        "python": (
            f"def {name}({py_params}):\n"
            "    # Explain your thinking as you code.\n"
            "    return None\n"
        ),
        "java": (
            "class Solution {\n"
            f"    public {java_signature} {{\n"
            "        // Explain your thinking as you code.\n"
            "        return null;\n"
            "    }\n"
            "}\n"
        ),
        "csharp": (
            "public class Solution\n"
            "{\n"
            f"    public {csharp_signature}\n"
            "    {\n"
            "        // Explain your thinking as you code.\n"
            "        return null;\n"
            "    }\n"
            "}\n"
        ),
    }


DEFAULT_CODING_PROBLEMS: list[dict[str, object]] = [
    {
        "id": "google-longest-unique-substring",
        "title": "Longest Unique Substring",
        "company": "Google",
        "difficulty": "medium",
        "prompt": (
            "Given a string s, return the length of the longest substring that contains no repeated characters. "
            "The solution should scale to long inputs without re-checking the same range over and over."
        ),
        "constraints": [
            "0 <= s.length <= 100000",
            "s may contain lowercase, uppercase, digits, spaces, and symbols",
        ],
        "examples": [
            {"input": 's = "abcabcbb"', "output": "3", "explanation": 'The answer is "abc".'},
            {"input": 's = "bbbbb"', "output": "1", "explanation": 'The answer is "b".'},
        ],
        "starter_code": _starter(
            "lengthOfLongestSubstring",
            "s: string",
            "s: str",
            "Integer lengthOfLongestSubstring(String s)",
            "int LengthOfLongestSubstring(string s)",
        ),
        "expected_topics": ["sliding window", "hash map", "two pointers"],
        "style_tags": ["strings", "incremental optimization", "windowing", "index bookkeeping"],
        "complexity_target": "Aim for O(n) time and O(min(n, alphabet)) space.",
        "edge_case_hints": ["empty string", "all characters identical", "repeated character at both ends"],
    },
    {
        "id": "meta-merge-intervals",
        "title": "Merge Busy Windows",
        "company": "Meta",
        "difficulty": "medium",
        "prompt": (
            "You are given a list of closed intervals where each interval represents a busy time window. "
            "Merge all overlapping intervals and return the condensed list sorted by start time."
        ),
        "constraints": [
            "1 <= intervals.length <= 100000",
            "0 <= start <= end <= 1000000",
        ],
        "examples": [
            {
                "input": "intervals = [[1,3],[2,6],[8,10],[15,18]]",
                "output": "[[1,6],[8,10],[15,18]]",
            },
            {
                "input": "intervals = [[1,4],[4,5]]",
                "output": "[[1,5]]",
            },
        ],
        "starter_code": _starter(
            "mergeIntervals",
            "intervals: number[][]",
            "intervals: list[list[int]]",
            "int[][] mergeIntervals(int[][] intervals)",
            "int[][] MergeIntervals(int[][] intervals)",
        ),
        "expected_topics": ["sorting", "interval sweep", "array traversal"],
        "style_tags": ["data cleanup", "ordered processing", "state carryover"],
        "complexity_target": "Expect O(n log n) time because sorting is usually required.",
        "edge_case_hints": ["single interval", "touching endpoints", "already sorted input"],
    },
    {
        "id": "amazon-top-k-frequent",
        "title": "Top K Frequent Items",
        "company": "Amazon",
        "difficulty": "medium",
        "prompt": (
            "Given an integer array nums and an integer k, return the k most frequent values. "
            "The order of the result does not matter."
        ),
        "constraints": [
            "1 <= nums.length <= 100000",
            "k is in the range [1, number of unique values]",
        ],
        "examples": [
            {"input": "nums = [1,1,1,2,2,3], k = 2", "output": "[1,2]"},
            {"input": "nums = [1], k = 1", "output": "[1]"},
        ],
        "starter_code": _starter(
            "topKFrequent",
            "nums: number[], k: number",
            "nums: list[int], k: int",
            "int[] topKFrequent(int[] nums, int k)",
            "int[] TopKFrequent(int[] nums, int k)",
        ),
        "expected_topics": ["hash map", "bucket sort or heap", "frequency counting"],
        "style_tags": ["ranking", "aggregation", "throughput", "tradeoffs"],
        "complexity_target": "Avoid repeatedly sorting the full array of frequencies if possible.",
        "edge_case_hints": ["all values unique", "k equals unique count", "negative numbers"],
    },
    {
        "id": "stripe-product-except-self",
        "title": "Product Except Self",
        "company": "Stripe",
        "difficulty": "medium",
        "prompt": (
            "Given an integer array nums, return an array answer where answer[i] is the product of all the elements "
            "of nums except nums[i]. Do not use division."
        ),
        "constraints": [
            "2 <= nums.length <= 100000",
            "-30 <= nums[i] <= 30",
        ],
        "examples": [
            {"input": "nums = [1,2,3,4]", "output": "[24,12,8,6]"},
            {"input": "nums = [-1,1,0,-3,3]", "output": "[0,0,9,0,0]"},
        ],
        "starter_code": _starter(
            "productExceptSelf",
            "nums: number[]",
            "nums: list[int]",
            "int[] productExceptSelf(int[] nums)",
            "int[] ProductExceptSelf(int[] nums)",
        ),
        "expected_topics": ["prefix products", "suffix products", "constant extra space"],
        "style_tags": ["financial correctness", "careful bookkeeping", "space optimization"],
        "complexity_target": "Target O(n) time and avoid allocating more than the output array if you can.",
        "edge_case_hints": ["zeros in the array", "negative numbers", "minimum length"],
    },
    {
        "id": "datadog-time-map",
        "title": "Time Based Key Value Store",
        "company": "Datadog",
        "difficulty": "medium",
        "prompt": (
            "Design a data structure that supports setting a value for a key at a timestamp and getting the most "
            "recent value for that key at or before a target timestamp."
        ),
        "constraints": [
            "Calls to set for the same key arrive in strictly increasing timestamp order",
            "Up to 200000 operations",
        ],
        "examples": [
            {
                "input": 'set("foo","bar",1), get("foo",1), get("foo",3)',
                "output": '"bar", "bar"',
            },
            {
                "input": 'set("foo","bar2",4), get("foo",4), get("foo",5)',
                "output": '"bar2", "bar2"',
            },
        ],
        "starter_code": {
            "typescript": (
                "export class TimeMap {\n"
                "  set(key: string, value: string, timestamp: number): void {\n"
                "    // Explain your thinking as you code.\n"
                "  }\n\n"
                "  get(key: string, timestamp: number): string {\n"
                '    return ""\n'
                "  }\n"
                "}\n"
            ),
            "javascript": (
                "export class TimeMap {\n"
                "  set(key, value, timestamp) {\n"
                "    // Explain your thinking as you code.\n"
                "  }\n\n"
                "  get(key, timestamp) {\n"
                '    return ""\n'
                "  }\n"
                "}\n"
            ),
            "python": (
                "class TimeMap:\n"
                "    def __init__(self):\n"
                "        # Explain your thinking as you code.\n"
                "        pass\n\n"
                "    def set(self, key: str, value: str, timestamp: int) -> None:\n"
                "        pass\n\n"
                "    def get(self, key: str, timestamp: int) -> str:\n"
                '        return ""\n'
            ),
            "java": (
                "class TimeMap {\n"
                "    public TimeMap() {}\n\n"
                "    public void set(String key, String value, int timestamp) {\n"
                "        // Explain your thinking as you code.\n"
                "    }\n\n"
                "    public String get(String key, int timestamp) {\n"
                '        return "";\n'
                "    }\n"
                "}\n"
            ),
            "csharp": (
                "public class TimeMap\n"
                "{\n"
                "    public TimeMap() {}\n\n"
                "    public void Set(string key, string value, int timestamp)\n"
                "    {\n"
                "        // Explain your thinking as you code.\n"
                "    }\n\n"
                "    public string Get(string key, int timestamp)\n"
                "    {\n"
                '        return "";\n'
                "    }\n"
                "}\n"
            ),
        },
        "expected_topics": ["binary search", "hash map", "append-only lists"],
        "style_tags": ["observability", "history lookup", "query efficiency", "design interview bridge"],
        "complexity_target": "set should be efficient, and get should avoid scanning the whole history.",
        "edge_case_hints": ["key not found", "timestamp before first value", "timestamp after latest value"],
    },
    {
        "id": "uber-alien-dictionary",
        "title": "Alien Dictionary Order",
        "company": "Uber",
        "difficulty": "hard",
        "prompt": (
            "You are given a sorted list of words from an unknown alphabet. Infer one valid character ordering. "
            "Return an empty string if the ordering is invalid."
        ),
        "constraints": [
            "1 <= words.length <= 100",
            "1 <= words[i].length <= 100",
        ],
        "examples": [
            {"input": 'words = ["wrt","wrf","er","ett","rftt"]', "output": '"wertf"'},
            {"input": 'words = ["z","x","z"]', "output": '""'},
        ],
        "starter_code": _starter(
            "alienOrder",
            "words: string[]",
            "words: list[str]",
            "String alienOrder(String[] words)",
            "string AlienOrder(string[] words)",
        ),
        "expected_topics": ["graph", "topological sort", "cycle detection"],
        "style_tags": ["dependency reasoning", "ordering constraints", "invalid state detection"],
        "complexity_target": "Build only the necessary graph edges and detect invalid prefixes early.",
        "edge_case_hints": ["prefix conflict", "disconnected letters", "cycle in dependencies"],
    },
    {
        "id": "netflix-lru-cache",
        "title": "LRU Cache",
        "company": "Netflix",
        "difficulty": "hard",
        "prompt": (
            "Implement an LRU cache that supports get and put in O(1) average time. "
            "When capacity is exceeded, evict the least recently used item."
        ),
        "constraints": [
            "1 <= capacity <= 3000",
            "Up to 200000 operations",
        ],
        "examples": [
            {
                "input": "LRUCache(2), put(1,1), put(2,2), get(1), put(3,3), get(2)",
                "output": "1, -1",
            }
        ],
        "starter_code": {
            "typescript": (
                "export class LRUCache {\n"
                "  constructor(capacity: number) {\n"
                "    // Explain your thinking as you code.\n"
                "  }\n\n"
                "  get(key: number): number {\n"
                "    return -1\n"
                "  }\n\n"
                "  put(key: number, value: number): void {}\n"
                "}\n"
            ),
            "javascript": (
                "export class LRUCache {\n"
                "  constructor(capacity) {\n"
                "    // Explain your thinking as you code.\n"
                "  }\n\n"
                "  get(key) {\n"
                "    return -1\n"
                "  }\n\n"
                "  put(key, value) {}\n"
                "}\n"
            ),
            "python": (
                "class LRUCache:\n"
                "    def __init__(self, capacity: int):\n"
                "        # Explain your thinking as you code.\n"
                "        pass\n\n"
                "    def get(self, key: int) -> int:\n"
                "        return -1\n\n"
                "    def put(self, key: int, value: int) -> None:\n"
                "        pass\n"
            ),
            "java": (
                "class LRUCache {\n"
                "    public LRUCache(int capacity) {}\n\n"
                "    public int get(int key) {\n"
                "        return -1;\n"
                "    }\n\n"
                "    public void put(int key, int value) {}\n"
                "}\n"
            ),
            "csharp": (
                "public class LRUCache\n"
                "{\n"
                "    public LRUCache(int capacity) {}\n\n"
                "    public int Get(int key)\n"
                "    {\n"
                "        return -1;\n"
                "    }\n\n"
                "    public void Put(int key, int value) {}\n"
                "}\n"
            ),
        },
        "expected_topics": ["hash map", "doubly linked list", "state synchronization"],
        "style_tags": ["systems thinking", "mutable state", "efficiency under pressure"],
        "complexity_target": "The interviewer will expect O(1) average time for both operations.",
        "edge_case_hints": ["capacity one", "updating existing key", "evicting the current tail"],
    },
]
