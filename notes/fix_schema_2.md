## Potential Issues

### 1

Suppose we have a text content for Chapter X. (Remarks/Preamble,Theorem_A_Statement, More Remarks/Preamble, Theorem_A_Proof) in this order.

Then Haikiu can make many valid tree structures. Our rules are to enforce the fundamental fact that we are not allowed to reorder the text. If we have separate preabmle in separate places that remains so.

See many valid examples, some nodes need not have content, they can just be structural.

```
>>> example_1
[{'id': 'ch_x', 'title': 'Chapter X', 'node_type': 'generic', 'parent_id': 'root', 'content': []}, {'id': 'ch_x_remarks', 'title': 'Chapter X', 'node_type': 'generic', 'parent_id': 'ch_x', 'content': ['Remarks/Preamble']}, {'id': 'ch_x_thm_a', 'title': 'Theorem A ', 'node_type': 'theorem', 'parent_id': 'ch_x', 'content': ['Theorem_A_Statement']}, {'id': 'ch_x_appropriate_title', 'title': 'Further Discussion', 'node_type': 'generic', 'parent_id': 'ch_x', 'content': ['More Remarks/Preamble']}, {'id': 'ch_x_thm_a_proof', 'title': 'Theorem A Proof', 'node_type': 'generic', 'parent_id': 'ch_x', 'content': ['Theorem_A_Proof']}]
>>> example_2
[{'id': 'ch_x', 'title': 'Chapter X', 'node_type': 'generic', 'parent_id': 'root', 'content': ['Remarks/Preamble']}, {'id': 'ch_x_thm_a', 'title': 'Theorem A ', 'node_type': 'theorem', 'parent_id': 'ch_x', 'content': ['Theorem_A_Statement']}, {'id': 'ch_x_appropriate_title', 'title': 'Further Discussion', 'node_type': 'generic', 'parent_id': 'ch_x', 'content': ['More Remarks/Preamble']}, {'id': 'ch_x_thm_a_proof', 'title': 'Theorem A Proof', 'node_type': 'generic', 'parent_id': 'ch_x', 'content': ['Theorem_A_Proof']}]
>>> example_3
[{'id': 'ch_x', 'title': 'Chapter X', 'node_type': 'generic', 'parent_id': 'root', 'content': ['Remarks/Preamble']}, {'id': 'ch_x_sec_thm_a', 'title': 'Theorem A', 'node_type': 'generic', 'parent_id': 'ch_x', 'content': []}, {'id': 'ch_x_thm_a', 'title': 'Theorem A ', 'node_type': 'theorem', 'parent_id': 'ch_x_sec_thm_a', 'content': ['Theorem_A_Statement']}, {'id': 'ch_x_appropriate_title', 'title': 'Further Discussion', 'node_type': 'generic', 'parent_id': 'ch_x_sec_thm_a', 'content': ['More Remarks/Preamble']}, {'id': 'ch_x_thm_a_proof', 'title': 'Theorem A Proof', 'node_type': 'generic', 'parent_id': 'ch_x_sec_thm_a', 'content': ['Theorem_A_Proof']}]
```

This example is illustrative, there may be more appropriate id, title, node_types

Would it be easier to have the output be a dict with id as the key and each element is {title:...,...,content:...,}? Or is the current list fine.

## Instruction / file reading issue

Your file reading proposal sounds reasonable.

Let's carefully plan and implement the changes. Make sure you understand my remarks in `###1`. If you have uncertainties ask, do not make assumptions.
