import katex from "katex";

function escapedAt(text, index) {
  let backslashes = 0;
  for (let cursor = index - 1; cursor >= 0 && text[cursor] === "\\"; cursor -= 1) {
    backslashes += 1;
  }
  return backslashes % 2 === 1;
}

function locationAt(text, index) {
  const prefix = text.slice(0, index);
  const lines = prefix.split("\n");
  return { line: lines.length, column: lines.at(-1).length + 1 };
}

function excludedCodeCharacters(markdown) {
  const excluded = new Uint8Array(markdown.length);
  let offset = 0;
  let fence = null;
  for (const line of markdown.split(/(?<=\n)/)) {
    const body = line.endsWith("\n") ? line.slice(0, -1) : line;
    const fenceMatch = body.match(/^ {0,3}(`{3,}|~{3,})/);
    if (fence) {
      excluded.fill(1, offset, offset + line.length);
      if (fenceMatch && fenceMatch[1][0] === fence.character
          && fenceMatch[1].length >= fence.length) {
        fence = null;
      }
      offset += line.length;
      continue;
    }
    if (fenceMatch) {
      excluded.fill(1, offset, offset + line.length);
      fence = { character: fenceMatch[1][0], length: fenceMatch[1].length };
      offset += line.length;
      continue;
    }

    for (let index = 0; index < body.length;) {
      if (body[index] !== "`" || escapedAt(body, index)) {
        index += 1;
        continue;
      }
      let run = 1;
      while (body[index + run] === "`") run += 1;
      const delimiter = "`".repeat(run);
      const close = body.indexOf(delimiter, index + run);
      if (close < 0) {
        index += run;
        continue;
      }
      excluded.fill(1, offset + index, offset + close + run);
      index = close + run;
    }
    offset += line.length;
  }
  return excluded;
}

function findClosing(markdown, excluded, start, delimiter, inlineDollar = false) {
  for (let index = start; index <= markdown.length - delimiter.length; index += 1) {
    if (excluded[index] || escapedAt(markdown, index)) continue;
    if (!markdown.startsWith(delimiter, index)) continue;
    if (inlineDollar && /\s/.test(markdown[index - 1] ?? "")) continue;
    return index;
  }
  return -1;
}

function extractMath(markdown) {
  const excluded = excludedCodeCharacters(markdown);
  const expressions = [];
  const errors = [];
  for (let index = 0; index < markdown.length;) {
    if (excluded[index]) {
      index += 1;
      continue;
    }

    let opening = null;
    let closing = null;
    let displayMode = false;
    if (markdown.startsWith("$$", index) && !escapedAt(markdown, index)) {
      opening = "$$";
      closing = "$$";
      displayMode = true;
    } else if (markdown[index] === "$" && !escapedAt(markdown, index)
               && markdown[index + 1] !== "$"
               && !/\s/.test(markdown[index + 1] ?? "")) {
      opening = "$";
      closing = "$";
    } else if (markdown.startsWith("\\(", index) && !escapedAt(markdown, index)) {
      opening = "\\(";
      closing = "\\)";
    } else if (markdown.startsWith("\\[", index) && !escapedAt(markdown, index)) {
      opening = "\\[";
      closing = "\\]";
      displayMode = true;
    }

    if (!opening) {
      index += 1;
      continue;
    }
    const contentStart = index + opening.length;
    const close = findClosing(
      markdown,
      excluded,
      contentStart,
      closing,
      opening === "$",
    );
    if (close < 0) {
      const location = locationAt(markdown, index);
      errors.push({
        ...location,
        code: "unclosed_math_delimiter",
        message: `Unclosed math delimiter ${opening}.`,
      });
      index = contentStart;
      continue;
    }
    expressions.push({
      start: index,
      contentStart,
      contentEnd: close,
      end: close + closing.length,
      displayMode,
    });
    index = close + closing.length;
  }
  return { expressions, errors };
}

function render(expression, displayMode) {
  const strictWarnings = [];
  try {
    katex.renderToString(expression, {
      displayMode,
      output: "mathml",
      throwOnError: true,
      strict: (code, message) => {
        strictWarnings.push({ code: `katex_strict_${code}`, message });
        return "ignore";
      },
      trust: false,
      maxExpand: 1000,
      macros: {},
      globalGroup: false,
    });
    return { valid: true, strictWarnings };
  } catch (error) {
    return {
      valid: false,
      strictWarnings,
      position: Number.isInteger(error?.position) ? error.position : 0,
    };
  }
}

function doubledCommandCandidates(expression) {
  const candidates = [];
  const pattern = /\\\\([A-Za-z]+)/g;
  for (const match of expression.matchAll(pattern)) {
    candidates.push({ index: match.index, command: match[1] });
  }
  return candidates;
}

function validateMarkdown(markdown) {
  const extraction = extractMath(markdown);
  const corrections = [];
  const warnings = [];
  const errors = [...extraction.errors];
  const replacements = [];

  for (const expression of extraction.expressions) {
    const original = markdown.slice(expression.contentStart, expression.contentEnd);
    const candidates = doubledCommandCandidates(original);
    const accepted = candidates.length
      ? original.replace(/\\\\([A-Za-z]+)/g, "\\$1")
      : original;
    const rendered = render(accepted, expression.displayMode);
    if (candidates.length) {
      replacements.push({
        start: expression.contentStart,
        end: expression.contentEnd,
        text: accepted,
      });
      for (const candidate of candidates) {
        const location = locationAt(
          markdown,
          expression.contentStart + candidate.index,
        );
        corrections.push({
          ...location,
          code: "doubled_tex_command_escape",
          command: candidate.command,
        });
      }
    }

    if (!rendered.valid) {
      const location = locationAt(
        markdown,
        expression.contentStart + (rendered.position ?? 0),
      );
      errors.push({
        ...location,
        code: "katex_parse_error",
        message: "KaTeX could not parse this math expression.",
      });
      continue;
    }
    for (const warning of rendered.strictWarnings) {
      const location = locationAt(markdown, expression.contentStart);
      warnings.push({
        ...location,
        code: warning.code,
        message: "KaTeX strict-mode compatibility warning.",
      });
    }
  }

  let normalizedText = markdown;
  for (const replacement of replacements.toReversed()) {
    normalizedText = normalizedText.slice(0, replacement.start)
      + replacement.text
      + normalizedText.slice(replacement.end);
  }
  return {
    normalizedText,
    expressionsChecked: extraction.expressions.length,
    corrections,
    warnings,
    errors,
  };
}

let input = "";
for await (const chunk of process.stdin) input += chunk;
const payload = JSON.parse(input);
if (typeof payload.markdown !== "string") throw new Error("markdown must be a string");
process.stdout.write(JSON.stringify(validateMarkdown(payload.markdown)));
