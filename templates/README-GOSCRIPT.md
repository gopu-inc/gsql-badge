
# Goscript Language Documentation

> **Version:** 2.0  
> **Repository:** [gopu-inc/gsql-badge](https://github.com/gopu-inc/gsql-badge)  
> **Package Manager:** [GPM](https://zenv-hub.onrender.com)  
> **Registry:** [Zarch Hub](https://zenv-hub.onrender.com)

---

## Table of Contents

1. [Introduction](#introduction)
2. [Installation](#installation)
3. [Basic Syntax](#basic-syntax)
4. [Variables & Constants](#variables--constants)
5. [Data Types](#data-types)
6. [Functions](#functions)
7. [Control Flow](#control-flow)
8. [Structs & Enums](#structs--enums)
9. [Pattern Matching](#pattern-matching)
10. [Async/Await](#asyncawait)
11. [FFI (Foreign Function Interface)](#ffi-foreign-function-interface)
12. [Modules & Imports](#modules--imports)
13. [Package Management (GPM)](#package-management-gpm)
14. [Standard Library](#standard-library)
15. [Error Handling](#error-handling)
16. [System Calls](#system-calls)
17. [F-Strings](#f-strings)
18. [CLI Arguments](#cli-arguments)
19. [Best Practices](#best-practices)
20. [Examples](#examples)
21. [Cheat Sheet](#cheat-sheet)

---

## Introduction

**Goscript** is a modern, fast, and expressive scripting language designed for system programming, automation, and the Zarch ecosystem. It combines the simplicity of scripting languages with the power of systems languages.

### Key Features

| Feature | Description |
|---------|-------------|
| `async/await` | Native asynchronous programming |
| `struct/enum/impl` | Object-oriented programming |
| `match` | Powerful pattern matching |
| `FFI` | Call C functions directly |
| `f-strings` | String interpolation with expressions |
| `try/catch` | Exception handling |
| `sysf/sh` | System command execution |
| `muts` | Mutable variables (explicit) |
| `nnl/jmp` | Non-local jumps |
| `unsafe` | Unsafe code blocks |

### Why Goscript?

- **Fast execution** - Compiled to native code
- **Small footprint** - Minimal runtime
- **C interoperability** - Call any C library via FFI
- **Modern syntax** - Clean, readable, expressive
- **Package ecosystem** - GPM and Zarch Hub

---

## Installation

### Prerequisites

- Linux (Alpine, Ubuntu, Debian, etc.)
- GCC or Clang
- libcurl, OpenSSL

### Quick Install

```bash
curl -sL https://zenv-hub.onrender.com/install.sh | sh
```

Manual Build

```bash
git clone https://github.com/gopu-inc/gsql-badge.git
cd gsql-badge
cmake .
make -j$(nproc)
make install
```

Verify Installation

```bash
goscript --version
# Output: Goscript v2.0

goscript --help
# Shows all options and usage
```

---

Basic Syntax

Hello World

```goscript
fn main() {
    println("Hello, World!")
    ret 0
}
```

Running a Script

```bash
goscript hello.gjs           # Run a script
goscript -d hello.gjs        # Run with AST debug output
goscript hello.gjs -- arg1   # Pass arguments
```

Comments

```goscript
// Single line comment

/*
   Multi-line
   comment
*/
```

Semicolons

Semicolons are optional. Use them to separate multiple statements on one line.

```goscript
lt a = 10
lt b = 20; lt c = 30  // Semicolons for same line
```

---

Variables & Constants

Immutable Variables (lt)

```goscript
lt name = "Goscript"
lt version = 2.0
lt is_active = true
```

Mutable Variables (muts)

```goscript
muts counter = 0
counter = counter + 1
counter += 5
```

Constants (cn)

```goscript
cn PI = 3.141592653589793
cn MAX_USERS = 1000
cn APP_NAME = "Zarch Hub"
```

Public Variables

```goscript
pub lt API_URL = "https://api.example.com"
pub cn VERSION = "2.0.0"
pub muts global_state = "initialized"
```

---

Data Types

Primitive Types

Type Example Description
int 42, -10, 0xFF Integer (hex, octal, binary supported)
float 3.14, -0.5, 1e10 Floating point
string "hello", 'world' Text string
bool true, false Boolean
nil nil Null/none value

Number Literals

```goscript
lt decimal = 42
lt hex = 0xFF          // 255
lt octal = 0o77        // 63
lt binary = 0b1010     // 10
lt float_num = 3.14159
lt scientific = 1.5e10
```

Strings

```goscript
lt single = 'Hello'
lt double = "World"
lt multi = '''
    Multi-line
    string
'''
lt template = f"Hello {name}"
```

Arrays

```goscript
lt numbers = [1, 2, 3, 4, 5]
lt mixed = [42, "hello", true, nil]
lt empty = []

// Access
lt first = numbers[0]
lt last = numbers[4]

// Modify (with muts)
muts arr = [1, 2, 3]
arr[1] = 99
```

Dictionaries (Maps)

```goscript
lt user = dict{
    "name" => "Alice",
    "age" => 30,
    "role" => "admin"
}

// Access
lt name = user["name"]
lt age = user["age"]

// Modify
user["email"] = "alice@example.com"
```

Dictionary Type Annotation

```goscript
fn process_users(users: dict<string, int>) {
    // users is a dictionary with string keys and int values
}
```

---

Functions

Basic Functions

```goscript
fn greet(name: string): string {
    ret "Hello, " + name + "!"
}
```

Multiple Parameters

```goscript
fn add(a: int, b: int): int {
    ret a + b
}
```

Optional Return Type

```goscript
fn log_message(msg: string) {
    println("[LOG] " + msg)
    // No return value (void)
}
```

Arrow Return (Short Form)

```goscript
fn get_name(user: User): string -> user.name
fn square(x: int): int -> x * x
```

Default Parameters

```goscript
fn greet(name: string, greeting: string = "Hello"): string {
    ret greeting + ", " + name + "!"
}

greet("Alice")              // "Hello, Alice!"
greet("Bob", "Welcome")     // "Welcome, Bob!"
```

Public Functions

```goscript
pub fn public_api(): string {
    ret "accessible from outside"
}

fn private_helper(): string {
    ret "internal only"
}
```

Async Functions

```goscript
async fn fetch_data(url: string): string {
    ret await f"curl -s '{url}'"
}

async fn process_parallel() {
    lt task1 = spawn fetch_data("https://api1.example.com")
    lt task2 = spawn fetch_data("https://api2.example.com")
    lt result1 = await task1
    lt result2 = await task2
    println(result1 + result2)
}
```

Lambda Functions

```goscript
lt add = lambda(x, y) { ret x + y }
lt result = add(10, 20)

// Inline lambda
lt doubled = [1, 2, 3]::map(lambda(x) { ret x * 2 })
```

---

Control Flow

If/Else

```goscript
lt score = 85

if score >= 90 {
    println("Grade: A")
} else if score >= 80 {
    println("Grade: B")
} else if score >= 70 {
    println("Grade: C")
} else {
    println("Grade: F")
}
```

Ternary Expression

```goscript
lt status = score >= 60 ? "pass" : "fail"
lt color = is_active ? "green" : "red"
```

While Loop

```goscript
muts i = 0
while i < 10 {
    println("Count: " + i)
    i = i + 1
    if i == 5 {
        continue  // Skip 5
    }
    if i == 8 {
        break    // Exit at 8
    }
}
```

For Loop

```goscript
// C-style for
for muts i = 0; i < 10; i = i + 1 {
    println("i = " + i)
}

// For-in (arrays)
for item in [1, 2, 3, 4, 5] {
    println("Item: " + item)
}

// For-in (strings)
for char in "Goscript" {
    println("Char: " + char)
}

// For-in (dictionaries)
for key, value in my_dict {
    println(key + " = " + value)
}

// For range
for i in 0..10 {
    println(i)  // 0 to 9
}

for i in 0..=10 {
    println(i)  // 0 to 10 (inclusive)
}
```

Loop (Infinite)

```goscript
muts count = 0
loop {
    println("Count: " + count)
    count = count + 1
    if count >= 5 {
        break
    }
}
```

Switch

```goscript
lt value = 42

switch value {
    case 1 => println("One")
    case 2 => println("Two")
    case 42 => println("The answer!")
    default => println("Something else")
}
```

---

Structs & Enums

Structs

```goscript
struct User {
    name: string,
    age: int,
    email: string
}

// Create instance
lt user = new User{
    name: "Alice",
    age: 30,
    email: "alice@example.com"
}

// Access fields
println(user.name)
println(user.age)

// Modify fields (with muts)
muts mutable_user = new User{ name: "Bob", age: 25, email: "bob@example.com" }
mutable_user.age = 26
```

Struct with Default Values

```goscript
struct Config {
    host: string = "localhost",
    port: int = 8080,
    debug: bool = false
}

lt config = new Config{ port: 3000 }
// host = "localhost", port = 3000, debug = false
```

Struct Inheritance

```goscript
struct Animal {
    name: string,
    age: int
}

struct Dog extends Animal {
    breed: string,
    bark_volume: int
}

lt dog = new Dog{
    name: "Rex",
    age: 3,
    breed: "German Shepherd",
    bark_volume: 10
}
```

Enums

```goscript
enm Color {
    Red,
    Green,
    Blue,
    Yellow
}

lt color = Color::Red

if color == Color::Red {
    println("It's red!")
}
```

Enum with Values

```goscript
enm Status {
    Active = 1,
    Inactive = 0,
    Pending = 2
}
```

Impl (Methods)

```goscript
struct Rectangle {
    width: int,
    height: int
}

impl Rectangle {
    fn area(self): int {
        ret self.width * self.height
    }
    
    fn perimeter(self): int {
        ret 2 * (self.width + self.height)
    }
    
    fn scale(self, factor: int) {
        self.width = self.width * factor
        self.height = self.height * factor
    }
}

lt rect = new Rectangle{ width: 10, height: 20 }
println(rect::area())        // 200
println(rect::perimeter())   // 60
```

---

Pattern Matching

Basic Match

```goscript
lt value = 42

match value {
    1 => println("One"),
    2 => println("Two"),
    42 => println("The Answer"),
    _ => println("Default")  // Wildcard
}
```

Match with Destructuring

```goscript
lt point = [10, 20]

match point {
    [0, 0] => println("Origin"),
    [0, y] => println("On Y axis: " + y),
    [x, 0] => println("On X axis: " + x),
    [x, y] => println("Point: (" + x + ", " + y + ")")
}
```

Match with Guards

```goscript
lt score = 85

match score {
    s where s >= 90 => println("A"),
    s where s >= 80 => println("B"),
    s where s >= 70 => println("C"),
    _ => println("F")
}
```

Match on Structs

```goscript
struct Point { x: int, y: int }

lt p = new Point{ x: 10, y: 20 }

match p {
    Point{ x: 0, y: 0 } => println("Origin"),
    Point{ x: 0, y: _ } => println("On Y axis"),
    Point{ x: _, y: 0 } => println("On X axis"),
    _ => println("Somewhere else")
}
```

---

Async/Await

Basic Async

```goscript
async fn fetch_user(id: int): string {
    ret await f"curl -s 'https://api.example.com/users/{id}'"
}

fn main() {
    lt user = fetch_user(42)
    println(user)
}
```

Multiple Async Operations

```goscript
async fn fetch_all() {
    lt task1 = spawn fetch_user(1)
    lt task2 = spawn fetch_user(2)
    lt task3 = spawn fetch_user(3)
    
    lt user1 = await task1
    lt user2 = await task2
    lt user3 = await task3
    
    println(user1 + user2 + user3)
}
```

Async with Error Handling

```goscript
async fn safe_fetch(url: string): string {
    try {
        ret await f"curl -s '{url}'"
    } catch (e) {
        println(f"Failed to fetch {url}: {e}")
        ret ""
    }
}
```

Promise-based

```goscript
async fn download_file(url: string, output: string) {
    lt result = await f"wget -O '{output}' '{url}'"
    if result == 0 {
        println("Download complete!")
    } else {
        println("Download failed")
    }
}
```

---

FFI (Foreign Function Interface)

Calling C Functions

```goscript
// Call libc functions directly
lt length = strlen_c("Goscript")       // 8
lt num = atoi_c("12345")              // 12345
lt now = time_c(nil)                   // Current timestamp

// File operations
lt file = fopen_c("test.txt", "w")
fprintf_c(file, "Hello, %s!", "World")
fclose_c(file)
```

Available C Functions

Goscript automatically binds many libc functions:

Category Functions
String strlen_c, strcmp_c, strcpy_c, strcat_c, strchr_c, strstr_c, strdup_c
Memory memcpy_c, memset_c, memcmp_c, malloc_c, calloc_c, realloc_c, free_c
Stdio fopen_c, fclose_c, fread_c, fwrite_c, fprintf_c, printf_c, scanf_c
Stdlib atoi_c, atof_c, system_c, getenv_c, setenv_c, exit_c
Math sin_c, cos_c, sqrt_c, pow_c, exp_c, log_c, ceil_c, floor_c
Time time_c, sleep_c, usleep_c
System fork_c, execv_c, wait_c, getpid_c, getuid_c
Network socket_c, bind_c, listen_c, accept_c, connect_c, send_c, recv_c

Custom FFI

```goscript
// Load custom library
lt lib = dlopen_c("libcustom.so", 1)
lt func = dlsym_c(lib, "my_function")

// Call with arguments
lt result = call_ffi(func, arg1, arg2)
```

---

Modules & Imports

Import Syntax

```goscript
// Basic import
import http

// Import with alias
import http as h

// Import from specific path
import utils from "./lib/utils"

// Import specific symbols
import fs { only: [read, write] }

// Import with timeout
import api { timeout: 5000 }

// Use statement (like Rust)
use ft::sleep
use ft::{sleep, now}
```

Creating a Module

```goscript
// lib/my_module.gjs
module my_module

pub fn public_function(): string {
    ret "I'm public"
}

fn private_function(): string {
    ret "I'm private"
}

pub cn MODULE_VERSION = "1.0.0"
```

Module with Submodules (Package)

```
my_package/
├── __self__.gjs       # Package entry point
├── utils.gjs          # my_package::utils
├── models.gjs         # my_package::models
└── services/
    ├── __self__.gjs   # my_package::services
    └── api.gjs        # my_package::services::api
```

Using Modules

```goscript
import my_package

// Access public functions
my_package::public_function()

// Access submodules
my_package::utils::helper()
my_package::services::api::fetch()
```

---

Package Management (GPM)

Creating a Package

```bash
gpm init my-awesome-package
```

This creates a Manifest.toml:

```toml
[metadata]
name = "my-awesome-package"
version = "1.0.0"
release = "r0"
arch = "x86_64"
description = "My awesome Goscript package"
author = "your-username"
license = "MIT"
main = "main.gjs"

[dependencies]
http = "^1.0"
fs = "*"

[dev-dependencies]
test-framework = "~0.5"

[scripts]
build = "gpm build"
test = "gpm run test.gjs"
```

Installing Packages

```bash
gpm install                    # Install all dependencies
gpm install http               # Install specific package
gpm install http@1.2.0         # Install specific version
gpm install --save-dev testlib # Install as dev dependency
```

Publishing

```bash
gpm login username password
gpm build
gpm publish
```

Version Constraints

Syntax Meaning
* Any version
latest Latest version
^1.2.3 Compatible with >=1.2.3 <2.0.0
~1.2.3 Approximately >=1.2.3 <1.3.0
>=1.2.3 Greater than or equal
<2.0.0 Less than
1.0.0 - 2.0.0 Range

---

Standard Library

Built-in Functions

Function Description
println(msg) Print with newline
print(msg) Print without newline
len(array) Get length
type_of(value) Get type name
abs(x) Absolute value
max(a, b) Maximum
min(a, b) Minimum
clamp(x, low, high) Clamp value
is_empty(s) Check if string empty
not_empty(s) Check if string not empty
contains(s, substr) Check if string contains
now() Current timestamp

Built-in Constants

```goscript
cn PI = 3.141592653589793
cn E = 2.718281828459045
cn VERSION = "2.0.0"
```

---

Error Handling

Try/Catch

```goscript
try {
    lt file = fopen_c("data.txt", "r")
    if file == nil {
        throw "Failed to open file"
    }
    // Process file...
    fclose_c(file)
} catch (e) {
    println("Error: " + e)
} finally {
    println("Cleanup done")
}
```

Raise/Except (Alternative Syntax)

```goscript
fn risky_operation(value: int): string {
    if value < 0 {
        raise "Value must be positive"
    }
    ret f"Value: {value}"
}

try {
    lt result = risky_operation(-5)
} except (e) {
    println(f"Caught: {e}")
}
```

Custom Error Types

```goscript
struct AppError {
    code: int,
    message: string
}

fn validate_input(input: string) {
    if input == "" {
        raise new AppError{ code: 400, message: "Input required" }
    }
}
```

---

System Calls

sysf - Capture Output

Returns the command output as a string.

```goscript
lt files = sysf("ls -la")
lt hostname = sysf("hostname")
lt date = sysf("date '+%Y-%m-%d'")

println("Hostname: " + hostname)
println("Files:\n" + files)
```

sh - Execute Only

Returns the exit code.

```goscript
lt code = sh("mkdir -p /tmp/test")
if code == 0 {
    println("Directory created")
} else {
    println("Failed")
}

// Condition
if sh("test -f /etc/passwd") == 0 {
    println("File exists")
}
```

Pipeline

```goscript
lt count = sysf("ls -1 | wc -l")
println("Files: " + count)
```

---

F-Strings

Basic Interpolation

```goscript
lt name = "Alice"
lt age = 30
lt msg = f"Hello {name}, you are {age} years old"
println(msg)  // "Hello Alice, you are 30 years old"
```

Expressions in F-Strings

```goscript
lt x = 10; lt y = 20
lt sum = f"{x} + {y} = {x + y}"
println(sum)  // "10 + 20 = 30"

lt status = f"User {name} is {'active' if is_active else 'inactive'}"
```

ANSI Colors in F-Strings

```goscript
lt name = "Goscript"
println(f"\033[32m✓ {name} v{VERSION}\033[0m")
println(f"\033[31m✗ Error: {error_msg}\033[0m")
```

Multiline F-Strings

```goscript
lt message = f'''
    Hello {name},
    
    Your account has {count} notifications.
    
    Regards,
    Zarch Hub Team
'''
```

---

CLI Arguments

Accessing Arguments

```goscript
fn main() {
    println("Number of arguments: " + len(ARGV))
    
    muts i = 0
    while i < len(ARGV) {
        println(f"ARGV[{i}] = {ARGV[i]}")
        i = i + 1
    }
}
```

Running with Arguments

```bash
goscript script.gjs arg1 arg2 arg3
# OR
goscript script.gjs -- arg1 arg2 arg3
```

---

Best Practices

1. Use lt by default, muts only when needed

```goscript
lt name = "Alice"        // Good: immutable
muts counter = 0         // Only when mutation needed
```

2. Type annotations for public APIs

```goscript
pub fn calculate(x: int, y: int): int {
    ret x * y + 10
}
```

3. Handle errors with try/catch

```goscript
try {
    lt content = sysf("cat file.txt")
    process(content)
} catch (e) {
    log_error(e)
}
```

4. Use async for I/O operations

```goscript
async fn main() {
    lt data = await fetch_from_api()
    process(data)
}
```

5. Organize code in modules

```
lib/
├── models.gjs
├── services.gjs
└── utils.gjs
```

6. Write tests

```goscript
// test.gjs
fn test_addition() {
    lt result = add(2, 3)
    assert(result == 5, "2 + 3 should equal 5")
}
```

7. Document your code

```goscript
// Calculates the factorial of n
// n must be non-negative
fn factorial(n: int): int {
    if n <= 1 { ret 1 }
    ret n * factorial(n - 1)
}
```

---

# Examples

# Example 1: HTTP Client

```goscript
module http_client

pub async fn get(url: string): string {
    try {
        lt response = await f"curl -s '{url}'"
        ret response
    } catch (e) {
        raise f"HTTP GET failed: {e}"
    }
}

pub async fn post(url: string, data: string): string {
    try {
        lt response = await f"curl -s -X POST -d '{data}' '{url}'"
        ret response
    } catch (e) {
        raise f"HTTP POST failed: {e}"
    }
}
```

# Example 2: File System Module

```goscript
module fs

pub fn exists(path: string): bool {
    ret sh(f"test -e '{path}'") == 0
}

pub fn is_file(path: string): bool {
    ret sh(f"test -f '{path}'") == 0
}

pub fn is_dir(path: string): bool {
    ret sh(f"test -d '{path}'") == 0
}

pub fn read(path: string): string {
    if !exists(path) {
        raise f"File not found: {path}"
    }
    ret sysf(f"cat '{path}'")
}

pub fn write(path: string, content: string) {
    sh(f"echo '{content}' > '{path}'")
}

pub fn mkdir(path: string) {
    sh(f"mkdir -p '{path}'")
}

pub fn ls(path: string): string {
    ret sysf(f"ls -la '{path}'")
}
```

# Example 3: Simple Web Server

```goscript
module server

struct Server {
    port: int,
    host: string
}

impl Server {
    pub fn new(port: int): Server {
        ret new Server{ port: port, host: "0.0.0.0" }
    }
    
    pub fn start(self) {
        println(f"Server starting on {self.host}:{self.port}")
        // Use netcat for simple server
        sh(f"while true; do echo 'HTTP/1.1 200 OK' | nc -l -p {self.port} -q 1; done")
    }
}

fn main() {
    lt server = Server::new(8080)
    server::start()
}
```

# Example 4: JSON Parser (Simple)

```goscript
module simple_json

struct JsonValue {
    raw: string
}

impl JsonValue {
    pub fn parse(json_str: string): JsonValue {
        ret new JsonValue{ raw: json_str }
    }
    
    pub fn get(self, key: string): string {
        lt cmd = f"echo '{self.raw}' | grep -o '\"{key}\"[[:space:]]*:[[:space:]]*\"[^\"]*\"' | head -1 | cut -d'\"' -f4"
        ret sysf(cmd)
    }
    
    pub fn get_int(self, key: string): int {
        lt val = self.get(key)
        ret atoi_c(val)
    }
}
```

# Example 5: Logger

```goscript
module logger

cn LOG_LEVELS = ["DEBUG", "INFO", "WARN", "ERROR"]
muts current_level = 1  // INFO

pub fn set_level(level: string) {
    muts i = 0
    while i < len(LOG_LEVELS) {
        if LOG_LEVELS[i] == level {
            current_level = i
            ret
        }
        i = i + 1
    }
}

pub fn debug(msg: string) {
    if current_level <= 0 {
        println(f"\033[35m[DEBUG]\033[0m {msg}")
    }
}

pub fn info(msg: string) {
    if current_level <= 1 {
        println(f"\033[34m[INFO]\033[0m {msg}")
    }
}

pub fn warn(msg: string) {
    if current_level <= 2 {
        println(f"\033[33m[WARN]\033[0m {msg}")
    }
}

pub fn error(msg: string) {
    if current_level <= 3 {
        println(f"\033[1;31m[ERROR]\033[0m {msg}")
    }
}
```

---

# Cheat Sheet

Variables

Syntax Description
lt x = 10 Immutable variable
muts x = 10 Mutable variable
cn X = 10 Constant
pub lt x = 10 Public variable

Functions

Syntax Description
fn name(): type { } Regular function
pub fn name() { } Public function
async fn name() { } Async function
fn name(): type -> expr Arrow return

Control Flow

Syntax Description
if cond { } else { } Conditional
cond ? a : b Ternary
while cond { } While loop
for i in arr { } For-in loop
loop { } Infinite loop
match val { case => expr } Pattern match
switch val { case => expr } Switch

Structs

Syntax Description
struct Name { fields } Struct definition
new Name{ values } Struct instantiation
struct A extends B { } Inheritance
impl Name { methods } Methods

Error Handling

Syntax Description
try { } catch (e) { } Try/catch
throw value Throw error
raise value Alternative throw
try { } except (e) { } Alternative catch

System

Syntax Description
sysf("cmd") Execute + capture output
sh("cmd") Execute, return code
await f"cmd" Async shell command
spawn expr Run in parallel

Imports

Syntax Description
import module Basic import
import module as alias Aliased import
import module { only: [a, b] } Selective import
use module::function Use statement

---

Resources

**· Official Registry**: Zarch Hub
**· Package Manager**: GPM Documentation
**· Community Forum**: Zarch Hub Forum
**· Source Code**: GitHub Repository
**· Issue Tracker**: GitHub Issues

---

# License

**Goscript is released under the MIT License.**

**Copyright (c) 2026 Gopu Inc.**

---

# Happy coding with Goscript! 🚀

