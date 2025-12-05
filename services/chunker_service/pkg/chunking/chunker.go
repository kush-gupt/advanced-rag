package chunking

import (
	"errors"
	"regexp"
	"strings"
	"unicode"
)

// Chunker defines the deterministic interface for turning text plus a
// ChunkingPlan into a sequence of Chunks.
type Chunker interface {
	Chunk(text string, plan ChunkingPlan, baseMeta map[string]interface{}) ([]Chunk, error)
}

// SlidingWindowChunker performs simple sliding-window chunking over
// characters, whitespace-delimited tokens, or lines depending on the
// ChunkingPlan. It is intentionally minimal and stateless so it can be
// used from other processes.
type SlidingWindowChunker struct{}

// NewSlidingWindowChunker constructs a new SlidingWindowChunker.
func NewSlidingWindowChunker() *SlidingWindowChunker {
	return &SlidingWindowChunker{}
}

// Chunk applies a sliding window over the provided text according to
// the plan. StartIndex and EndIndex are expressed in unit indices
// (characters, tokens, or lines depending on Mode).
func (c *SlidingWindowChunker) Chunk(
	text string,
	plan ChunkingPlan,
	baseMeta map[string]interface{},
) ([]Chunk, error) {
	if plan.WindowSize <= 0 {
		return nil, errors.New("window_size must be > 0")
	}
	if plan.Overlap < 0 || plan.Overlap >= plan.WindowSize {
		return nil, errors.New("overlap must be >= 0 and < window_size")
	}

	var units []string
	switch plan.Mode {
	case ModeTokens:
		units = strings.Fields(text)
	case ModeLines:
		units = strings.Split(text, "\n")
	case ModeCharacters, "":
		// Default to characters (bytes for now). Runes can be added later
		// if needed, but for many test cases this is sufficient.
		units = make([]string, 0, len(text))
		for i := 0; i < len(text); i++ {
			units = append(units, text[i:i+1])
		}
	default:
		return nil, errors.New("unsupported mode")
	}

	if len(units) == 0 {
		return nil, nil
	}

	step := plan.WindowSize - plan.Overlap
	if step <= 0 {
		// Should be prevented by the validation above, but guard anyway.
		return nil, errors.New("invalid step size computed from window_size and overlap")
	}

	segments := []segment{{start: 0, end: len(units), heading: "", level: 0}}
	if plan.BreakOnHeadings && plan.Mode == ModeLines {
		segments = headingSegments(units)
	}

	var chunks []Chunk
	for _, seg := range segments {
		for start := seg.start; start < seg.end; start += step {
			end := start + plan.WindowSize
			if end > seg.end {
				end = seg.end
			}

			window := units[start:end]
			textChunk := ""
			switch plan.Mode {
			case ModeTokens:
				textChunk = strings.Join(window, " ")
			case ModeLines:
				windowLines := window
				if plan.IncludeHeadings && seg.heading != "" && start == seg.start && len(windowLines) > 0 {
					windowLines = windowLines[1:]
				}
				textChunk = strings.Join(windowLines, "\n")
			default:
				textChunk = strings.Join(window, "")
			}

			chunk := Chunk{
				Text:       textChunk,
				StartIndex: start,
				EndIndex:   end,
				Extra:      map[string]interface{}{},
			}

			if plan.Mode == ModeLines && seg.heading != "" {
				chunk.Extra["heading"] = seg.heading
				if seg.level > 0 {
					chunk.Extra["heading_level"] = seg.level
				}
				if plan.IncludeHeadings {
					chunk.Text = seg.heading + "\n" + chunk.Text
				}
			}

			if v, ok := baseMeta["file_name"].(string); ok {
				chunk.FileName = v
			}
			if v, ok := baseMeta["file_path"].(string); ok {
				chunk.FilePath = v
			}
			if v, ok := baseMeta["mime_type"].(string); ok {
				chunk.MimeType = v
			}

			for k, v := range baseMeta {
				if k == "file_name" || k == "file_path" || k == "mime_type" {
					continue
				}
				chunk.Extra[k] = v
			}

			chunks = append(chunks, chunk)

			if end == seg.end {
				break
			}
		}
	}

	if plan.MaxChunks > 0 && len(chunks) > plan.MaxChunks {
		chunks = chunks[:plan.MaxChunks]
	}

	return chunks, nil
}

var headingNumberPattern = regexp.MustCompile(`^[0-9]+(\.[0-9]+)*[.)]?\s+`)

// headingSegments returns contiguous line ranges that begin at likely headings.
// This keeps sliding windows from crossing major sections when requested.
type segment struct {
	start   int
	end     int
	heading string
	level   int
}

func headingSegments(lines []string) []segment {
	var segments []segment

	start := 0
	headingText, headingLevel := headingInfo(lines[0])
	for i, line := range lines {
		if i == 0 {
			continue
		}
		if isHeading(line) {
			segments = append(segments, segment{start: start, end: i, heading: headingText, level: headingLevel})
			headingText, headingLevel = headingInfo(line)
			start = i
		}
	}
	if start < len(lines) {
		segments = append(segments, segment{start: start, end: len(lines), heading: headingText, level: headingLevel})
	}
	return segments
}

func isHeading(line string) bool {
	trimmed := strings.TrimSpace(line)
	if trimmed == "" {
		return false
	}
	if strings.HasPrefix(trimmed, "#") {
		return true
	}
	if headingNumberPattern.MatchString(trimmed) {
		return true
	}
	// Treat short, mostly-uppercase lines as headings (common in PDFs/MD).
	if len([]rune(trimmed)) <= 80 {
		totalLetters := 0
		upperLetters := 0
		for _, r := range trimmed {
			if unicode.IsLetter(r) {
				totalLetters++
				if unicode.IsUpper(r) {
					upperLetters++
				}
			}
		}
		if totalLetters > 0 && float64(upperLetters) >= 0.6*float64(totalLetters) {
			return true
		}
	}
	return false
}

func headingInfo(line string) (string, int) {
	if !isHeading(line) {
		return "", 0
	}
	trimmed := strings.TrimSpace(line)
	if strings.HasPrefix(trimmed, "#") {
		level := 0
		for i := 0; i < len(trimmed) && trimmed[i] == '#'; i++ {
			level++
		}
		return strings.TrimSpace(trimmed[level:]), level
	}
	if headingNumberPattern.MatchString(trimmed) {
		return trimmed, 1
	}
	// Uppercase short heading
	return trimmed, 1
}
