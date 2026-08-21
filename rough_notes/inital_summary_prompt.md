This project aims to clean and parse mathematics/science text and create a tree representing the text.

The specific instance we plan to have is parse the MinerU generated markdown file.

The overall ideas is that Haiku (or Sonnet if the specified by option/config) via "claude -p prompt" parses chunks of text using a task_skill.md (see `~/ai_tool_development/claude_text_parser/prompt/task_skill.md`) specifying how to do things. Therefore Haiku ends up reading the entire raw text and fixes any latex errors or AI scan mistakes whilst keeping true to the original text. Note that we must use this claude code -p method since we have claude code NOT the API (see line 351 of `~/ai_tool_development/claude_text_parser/orchestrator.py`)

There is a previous project POC implementation of this at `/home/jake/ai_tool_development/claude_text_parser`.

There will still be a state representing the current state of parsing (see the hierarchy.json, progress.json, theory.json files in `~/ai_tool_development/knowledge_prasing/attempt_states/a1`). In our previous project POC you could specify the location of where the in progress state would be. We still want this however

- There will no longer be a separate theory|hierarchy.json objects. There will be one hierarchy where theory nodes are a subtype of Node. Nodes will point to parsed content.
- Can we specify the location where the state dir is (create if needed) and also git track. So when Haiku adds a new chunk.md file and updates the json file the git tracking adds and commits every time.
- State will be implemented in this domain/ports/adapters hexagonal architecture.

A general thought.

- Suppose we have a section of a text "Chapter 2 Section 1 - Definition of Vector space" which has some text and then the formal definition of the vector space. The node that represents this chapter is of type Generic. The child node that is of type Definition is the definition and nothing more. Any preamble or discussion of what the definition means is elsewhere in the Tree. Therefore theory nodes are just that exact theory component like you often have in math texts. I think the previous project attempting this was able to do it.

This current project has just implemented the domain logic for these Node trees in python. Later I will consider cool things like using the domain representation of text to product different renderings. Understand the current structure and implementation of this new project, notes.md may help.

After understanding our next job is to plan and implement part 2, the ability to parse the raw/ text and create the tree that we are able to use in the domain.

With this propose a new structure for this repository that uses the hexagonal domain, ports, adapters architecture. We want the most clean logical structure.

Follow good practices like logging and not just printing.

If you have any questions, concerns, can see any inconsistencies or mistakes in my ideas then ask me. We do not want to make any assumptions or sources of uncertainty.

Guide me through key decisions/structural ideas. I do not want tech debt in my understanding of our project.

# My Responses

## Q1

The chunks e.g `~/ai_tool_development/knowledge_prasing/attempt_states/a1/chunks/chunk_000.md` are just the raw content post cleaning. They are often long since Haiku may as well process a large batch. Each node has a list of Content. In our specific chunk_lines adapter Content class each piece of content points to an interval of lines in the chunk .md file. So a theory node, and any other node that has content, just points to a subset of lines in the chunk. Technically that subset could be the full chunk but that is unlikely.

## Q2

Let's have Haiku write the .md file directly. It is safer than putting markdown and latex characters that could break in json. Each time Haiku is called it saves a new (chunk_{id + 1}.md usually) file so nothing good is being written over.

## Q3

Yes the state dir should always be a separate git repo. Previously I had the working state dir in another location to the project repo.

## Q4

Let's keep this Phase 0 and be very careful that these nodes do eventually get populated. Should we give the user the option to Specify a better model for Phase 0? Should we give Haiku the option to rarefactor the overall hierarchy of the state if later in the text more information comes to light?

## Q5

Can Haiku assign them and uniqueness is encouraged since Haiuku can see the current State in json form and therfore see the previous nodes? Or was Haiuku not able to see the State in json form?

## Q6

Let's resolve dependancies at the end.
Do we want some logic where queries are passed to Haiku at the end if dependancies are missing? or is that to open a problem?

# After responces

I agree regarding Q4.

Re Q5, should we log and retry with a concise extra addition to the Haiku prompt not to make that name mistake.

Re Q6 I agree. We can save the final tree and a report.

On your one more question let's pick Option A. Haiku will have to read the json anyway so include in the prompt.
