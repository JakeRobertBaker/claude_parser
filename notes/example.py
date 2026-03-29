example_1 = [
    {
        "id": "ch_x",
        "title": "Chapter X",
        "node_type": "generic",
        "parent_id": "root",
        "content": [],
    },
    {
        "id": "ch_x_remarks",
        "title": "Chapter X",
        "node_type": "generic",
        "parent_id": "ch_x",
        "content": ["Remarks/Preamble"],
    },
    {
        "id": "ch_x_thm_a",
        "title": "Theorem A ",
        "node_type": "theorem",
        "parent_id": "ch_x",
        "content": ["Theorem_A_Statement"],
    },
    {
        "id": "ch_x_appropriate_title",
        "title": "Further Discussion",
        "node_type": "generic",
        # maybe node type remarks
        "parent_id": "ch_x",
        "content": ["More Remarks/Preamble"],
    },
    {
        "id": "ch_x_thm_a_proof",
        "title": "Theorem A Proof",
        "node_type": "generic",
        "parent_id": "ch_x",
        "content": ["Theorem_A_Proof"],
    },
]

example_2 = [
    {
        "id": "ch_x",
        "title": "Chapter X",
        "node_type": "generic",
        "parent_id": "root",
        "content": ["Remarks/Preamble"],
    },
    {
        "id": "ch_x_thm_a",
        "title": "Theorem A ",
        "node_type": "theorem",
        "parent_id": "ch_x",
        "content": ["Theorem_A_Statement"],
    },
    {
        "id": "ch_x_appropriate_title",
        "title": "Further Discussion",
        "node_type": "generic",
        "parent_id": "ch_x",
        "content": ["More Remarks/Preamble"],
    },
    {
        "id": "ch_x_thm_a_proof",
        "title": "Theorem A Proof",
        "node_type": "generic",
        "parent_id": "ch_x",
        "content": ["Theorem_A_Proof"],
    },
]


example_3 = [
    {
        "id": "ch_x",
        "title": "Chapter X",
        "node_type": "generic",
        "parent_id": "root",
        "content": ["Remarks/Preamble"],
    },
    {
        "id": "ch_x_sec_thm_a",
        "title": "Theorem A",
        "node_type": "generic",
        "parent_id": "ch_x",
        "content": [],
    },
    {
        "id": "ch_x_thm_a",
        "title": "Theorem A ",
        "node_type": "theorem",
        "parent_id": "ch_x_sec_thm_a",
        "content": ["Theorem_A_Statement"],
    },
    {
        "id": "ch_x_appropriate_title",
        "title": "Further Discussion",
        "node_type": "generic",
        "parent_id": "ch_x_sec_thm_a",
        "content": ["More Remarks/Preamble"],
    },
    {
        "id": "ch_x_thm_a_proof",
        "title": "Theorem A Proof",
        "node_type": "generic",
        "parent_id": "ch_x_sec_thm_a",
        "content": ["Theorem_A_Proof"],
    },
]
