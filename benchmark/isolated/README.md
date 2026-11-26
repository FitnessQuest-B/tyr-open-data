# Offline external-agent runner

The verification and pilot suites use the TYR Open Data 0.1.0 records projection and the existing observation task and submission JSON. The reference profile uses a CPU-only Linux arm64 guest, rootless Podman, and a fresh QEMU disk overlay per case. Use the [bundled benchmark](../README.md) for a quick smoke test without a VM.

## Trust boundary

Keep the evaluator and guest setup workspace outside the checkout. A trusted host supervisor stages one synthetic observation packet and [the task contract](../task.md) on read-only virtual media. The guest has no network interface or host shares. Rootless Podman gives the agent a read-only filesystem, non-root UID, a private network namespace, bounded scratch and output, and CPU, memory and process caps. The host collects a bounded submission and discards the guest. The guest receives only this case, the agent image and the trusted supervisor. The host, QEMU, guest image and supervisor are trusted. Verification applies to the documented runner profile.

A rootless OCI image can supply an offline agent entry point that accepts the packet directory as its final argument. It must print exactly one submission object to stdout and may put bounded diagnostics on stderr. Use the original submission schema with `provider: null`. The reference image uses the experimental evidence-aware weight and sleep method. Additional images can be preloaded in the disposable installation guest as the `tyrworker` user during setup, before making the frozen image. Pass their full image IDs with `--image` and use the same CPU-only limits. Agent archives and evaluator material should be handled separately. The runner never pulls during case execution.

## Prepare the guest

The reference setup was exercised on Apple silicon with QEMU's HVF accelerator. Start with an Ubuntu 24.04 minimal arm64 cloud image and verify it against the publisher's checksum. The setup guest uses networking to install the runtime and the public Python reference image. Use a dedicated workspace containing only the public setup inputs. [Ubuntu arm64 cloud images](https://cloud-images.ubuntu.com/minimal/releases/noble/release/) · [Rootless Podman run options](https://docs.podman.io/en/latest/markdown/podman-run.1.html)

From the checkout, with `work` set to a fresh private directory and `base` and `firmware` set to the verified image and arm64 EDK2 firmware paths:

```sh
python3 -B benchmark/isolated/provision_guest.py "$work/seed"
hdiutil makehybrid -quiet -iso -joliet -default-volume-name CIDATA \
  -o "$work/seed.iso" "$work/seed"
qemu-img create -q -f qcow2 -F qcow2 -b "$base" "$work/install.qcow2" 9G
qemu-system-aarch64 -machine virt,accel=hvf -cpu host -m 3072 -smp 2 \
  -nodefaults -no-reboot -display none -monitor none -serial stdio -bios "$firmware" \
  -drive "if=virtio,format=qcow2,file=$work/install.qcow2" \
  -drive "if=virtio,format=raw,readonly=on,file=$work/seed.iso" \
  -nic user,model=virtio-net-pci > "$work/provision.log" 2>&1
```

Check for `TYR_PROVISION_READY` in the setup log. Configuration first uses the trusted public guest to export its installed ARM64 kernel, optional initrd, and root partition UUID. That extraction uses the supplied UEFI firmware and a setup-only transfer disk. Subsequent builds, probes, and case VMs boot Linux directly using the pinned boot files. Configuration builds the allowlisted reference worker offline, flattens and fingerprints the guest disk, and writes the profile.

Direct boot bypasses the EFI path where an intermittent boot exception was observed. The exact triggering defect remains unconfirmed. Provisioning resolves public Ubuntu packages and a base container image, so rebuilding later may yield a different profile. Preserve the frozen profile and its recorded hashes for exact replays.

```sh
python3 -B benchmark/isolated/runner.py configure \
  --install-disk "$work/install.qcow2" --qemu "$(command -v qemu-system-aarch64)" \
  --firmware "$firmware" --profile "$work/profile.json"
python3 -B benchmark/pilot.py prepare "$work/development" --development
python3 -B benchmark/pilot.py audit "$work/development"
```

Choose one packet directory under `$work/development/agent` for `public_packet` and qualify the frozen profile:

```sh
python3 -B benchmark/isolated/runner.py probe --profile "$work/profile.json" \
  --packet "$public_packet" --output "$work/probes.json"
```

A valid reference submission, two fresh control probes, missing input and result device probes, timeout and output-cap probes, and malformed-submission rejection are required. The profile binds the guest disk, kernel, optional initrd, trusted supervisor and launch policy. A launch-policy change requires configuring and probing a fresh profile.

The supervisor waits for the control disk, input disk and result device. The host allows 35 seconds for the readiness marker, then 115 seconds for guest execution, eight seconds from the result marker for delivery, and ten seconds from the complete frame for shutdown. Each agent has a separate 90-second execution limit. Host receipts report the last phase, termination status, byte counts and trusted boot milestones from a bounded console separate from the result stream. The timeout canary verifies that an over-budget agent can still return a complete receipt. A missing device must fail without a submission.

The guest uses cgroup v2 with systemd delegation and an enforced seccomp profile. The pilot runner requires a verified profile and a passing audit of the frozen private suite.

## Compare the v0.2.0 and v0.3.0 workers

Pass a local checkout with the published v0.2.0 Git object to `configure --baseline-source`. The builder reads the baseline inputs directly from commit `b6bb546` and builds both worker images offline in the installation guest before freezing one disk. The profile lists the two distinct image IDs.

Revision 5 evaluates reassessment on a 96-case suite. Set `baseline_source` to the clean v0.2.0 checkout and use a new workspace for the public panel.

```sh
python3 -B benchmark/verification.py prepare "$work/public-panel" --revision 5 --development
python3 -B benchmark/verification.py audit "$work/public-panel" \
  --output "$work/public-panel/evaluator/audit.json"
python3 -B benchmark/verification.py calibrate "$work/public-panel" \
  --baseline-source "$baseline_source" --output "$work/calibration.json"
```

After public calibration and runner qualification pass, prepare a fresh private workspace and audit it before any predictions.

```sh
python3 -B benchmark/verification.py prepare "$work/verification" --revision 5 \
  --calibration "$work/calibration.json"
python3 -B benchmark/verification.py audit "$work/verification" \
  --output "$work/verification/evaluator/audit.json"
```

The audit checks the exact transition quotas, evidence support, and metadata-only baselines. Keep the private index, truth, audit, and results separate from the packet directory and source checkout. These suites validate deterministic synthetic methods. The offline runner can host external worker programs, and the reported evaluations used only the deterministic workers.

The revision 4 120-case suite and scoring remain available. It uses the existing default `prepare` revision. Add `--development` to generate its public fixtures.

Run the documented public canaries before evaluation. Run `runner.py run` twice with the same profile, agent root, index and audit, using separate result directories. Select each pinned image with `--image`. For revisions 4 and 5 the audit fixes eight replays before execution. Compare complete receipt sets using:

```sh
python3 -B benchmark/verification.py score --workspace "$work/verification" \
  --baseline "$work/baseline-runs" --candidate "$work/candidate-runs" \
  --profile "$work/profile.json" --audit "$work/verification/evaluator/audit.json" \
  --output "$work/verification/evaluator/comparison.json"
```

The candidate checks local observations around the nominated weight dates and requires agreement between separated blocks before making a change call. For reassessment, it compares the halves of each window under a shared mix of eligible strata and withholds decisive labels when the within-window evidence supports different directions around the threshold. Exact before-and-after windows and direction still determine credit. The comparator records abstention, control accuracy, exact transitions and extra calls separately. Treat all results as synthetic method evaluation.

## Run the revision 3 pilot

Use a new evaluator-owned workspace. Keep case labels, parameters, seeds, diagnostics and detailed scores in it.

```sh
python3 -B benchmark/pilot.py prepare "$work/pilot"
python3 -B benchmark/pilot.py audit "$work/pilot" --output "$work/suite-audit.json"
python3 -B benchmark/isolated/runner.py run --profile "$work/profile.json" \
  --probe "$work/probes.json" --suite-audit "$work/suite-audit.json" \
  --agent-root "$work/pilot/agent" --index "$work/pilot/evaluator/index.json" \
  --output "$work/runs" --jobs 2
python3 -B benchmark/pilot.py score "$work/pilot" "$work/runs" \
  --output "$work/pilot/evaluator/pilot-score.json"
```

The 48-case suite varies layouts and has an independent leave-one-case-out calendar and position baseline. All three sleep decision labels must appear in every position and length band, and layout-only macro recall must be at most 0.53. The emitted records must support at least four transitions from supported to not supported and four in the reverse direction. Changing and stable cases share the same calendar sampler and stratified timing assignment. Sparse controls exercise coverage-based abstention. A failed audit requires reviewing the suite design. Fresh seeds are private and can be replayed from a private seed file.

Sleep labels use emitted positive-dose and next-wake records. An adequate window has at least 30 pairs, 50% coverage and ten observations in each timing arm. Training and weekend strata need at least three observations per arm to contribute to common support. The retained strata must cover at least half the pairs and ten observations per arm. Effects within two minutes of the 15-minute threshold, or mixed regimes whose expected contrasts differ by more than ten minutes, are inconclusive. Simulated mechanisms, expected observable contrasts and evidence adequacy are recorded separately.

Weight labels require at least twelve recorded values in each observation quarter. Known synthetic shifts also need twelve observations in each neighboring 42-day band. Shifts from 0.8 through 1.2 kg enter a gray zone. Gradual drift is a comparison case for the abrupt-breakpoint target. A decisive breakpoint must be within 14 days and have the expected direction. These rules apply to the synthetic pilot.

The experimental detector selects a candidate breakpoint on alternating calendar weeks by comparing a straight-line trend with a straight-line trend plus a level step. It checks the same date on the other weeks. Both fits must agree in sign, estimate a step of at least 1 kg and reduce residual squared error by at least 20%. It returns no change when coverage supports the search and all eligible adjusted steps in both groups are below 0.8 kg. Other outcomes are inconclusive. This checks sensitivity to withholding blocks from date selection. Serial dependence can remain between the blocks, and the method has only been exercised on synthetic records. Nonlinear drift, multiple steps and measurement changes can violate its assumptions.

The score report uses an always-abstain reference and groups results by synthetic case family. Malformed, failed and timed-out submissions receive zero credit in the attempted-case denominator. A paired case bootstrap describes uncertainty in the pilot credit difference. Use these results to validate the method and examine errors. The case design and pilot sample size support that purpose.

The reassessment diagnostic compares consecutive decisive assessments. An inconclusive window can sit between them. Credit requires the same before and after windows and the same change in direction as the expected sequence.
