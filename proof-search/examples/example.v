Require Import Coq.Unicode.Utf8.
Require Import List.
Require Import ZArith.

From Coq Require Import ZArith Lia.

Open Scope Z_scope.

Ltac reduce_eq := simpl; reflexivity.

Lemma orb_true_l : forall b : bool, orb true b = true.
Proof.
  intros b.
  simpl.
  reflexivity.
  Qed.