Require Import Stdlib.Unicode.Utf8.
From Stdlib Require Import List.
From Stdlib Require Import ZArith.

From Stdlib Require Import ZArith Lia.

Open Scope Z_scope.

Ltac reduce_eq := simpl; reflexivity.

Lemma orb_true_l : forall b : bool, orb true b = true.
Proof.
  intros b.
  simpl.
  reflexivity.
  Qed.