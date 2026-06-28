"""CAD-Copilot evaluation harness (M1-W2-EVAL-02).

Drives the real pipeline endpoints and scores them against bench/cases. Built before the
engines it measures — accuracy is the paramount, non-negotiable requirement, so the measuring
stick comes first. Kernel-dependent metrics (IoU/Chamfer/execution) are placeholders until the
geometry kernel lands (M2-W6); everything else is live now.
"""
