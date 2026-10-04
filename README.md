# synthero

Makes synthetic copies of a scanned invoice or receipt, with new personal data
and numbers, and writes an answer key for each copy.

1. Qwen3-VL (local llama-server) finds every text line and its box.
2. Qwen3-VL labels the lines that hold customer or transaction data.
3. Code invents new values that keep each value's format.
4. Each changed line is redrawn inside its own box and pasted back with a soft
   edge. Pixels outside the boxes are copied unchanged, so edits do not degrade
   the rest of the scan.
5. Qwen3-VL reads each new box back to check it.

```sh
python3 -m synthero SCAN.png --n 3          # outputs go to /dev/shm/synthero/out
```

It needs a vision llama-server (tested: Qwen3.8-27B Q6_K with its mmproj) at
`SYNTHERO_VL` (default `http://127.0.0.1:18930`).

Prototype. Outputs are synthetic test data; never commit them.
