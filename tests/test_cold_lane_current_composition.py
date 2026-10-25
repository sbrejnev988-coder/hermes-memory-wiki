"""Current COLD file composition and explicit old41 isolation, SOURCE only.

Prepared SOURCE: own credential-free homes/TMPDIR, python -I -B -S; explicit
retained COLD transports are required for the historical baseline controls.
The existing SOURCE bootstrap may supply the same independent compressed byte
census used by ColdPartitionTests; none of the classified files is executed.
main reuses that exact whole module/main/TestCase/reporter before this suite.
Pytest marker is the standard nonselection contract, not actual collection proof.
The embedded d4 descriptor is a raw-pinned historical input, not native authority.
"""
from __future__ import annotations
import ast
import base64
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import types
import unittest
import zlib

__test__ = False
ROOT = Path(__file__).absolute().parents[1]
SELF = 'tests/test_cold_lane_current_composition.py'
OLD = 'tests/test_cold_lane_partition.py'
OLD_SHA256 = '96097117a11b6c2ca94183e32fe012b08598eebcaa59d889b3bf7f6d8af54669'
BASELINE_SHA256 = 'fbd512127d0de3ac07ca659f6128db52e79ad092ebd1a41cfa95cbb46ffa851e'
MARKER = b'    # Explicit stdlib SOURCE only: setUpClass and the suite require no SDK preload.\n    __test__ = False\n\n'
OLD_ROSTER = ('test_actual_fixture_absence_guard_drift_refused_after_rehash', 'test_actual_inherited_fixture_alias_drift_refused_after_rehash', 'test_current_delivered_ci_dispatch_peer_is_bound', 'test_current_full_file_and_entry_closure', 'test_distinct_core_targets_match_actual_declared_entry_constants', 'test_duplicate_partition_path_refused', 'test_existing_cold_plan_refuses_pending_rebind_and_missing_origins', 'test_explicit_callable_signature_is_bound_to_actual_source', 'test_explicit_unittest_setup_is_declared_not_counted_as_pytest', 'test_inherited_fixture_binding_cannot_be_omitted_or_redirected', 'test_inherited_fixture_refuses_native_metadata_even_with_false_absence', 'test_inherited_stage_fixture_uses_actual_absence_lane', 'test_invalid_literal_paths_and_hashes_refused', 'test_inventory_digest_count_and_provider_pin_cannot_diverge', 'test_isolated_ci_actual_initial_import_drift_refused_after_rehash', 'test_isolated_ci_bare_and_mutated_bootstrap_refused', 'test_isolated_ci_invocation_binds_actual_initial_import', 'test_isolated_ci_missing_prerequisites_and_peer_refused', 'test_isolated_ci_runpy_executes_path_binding_before_entry', 'test_isolated_ci_runpy_preserves_exact_target_argv', 'test_isolated_ci_runpy_selects_actual_stdlib_unittest_suite', 'test_metadata_only_is_not_source_or_native_attestation', 'test_missing_current_file_refused_even_after_metadata_recount', 'test_missing_declared_peer_and_prerequisite_refused', 'test_missing_source_input_refused', 'test_native_and_trust_admission_remain_genuinely_unresolved', 'test_native_target_loss_duplication_and_wrong_lane_refused', 'test_peer_hash_is_null_until_actual_delivery', 'test_peer_input_edge_alone_does_not_inherit_fixture_absence', 'test_sdk_absence_source_targets_cannot_enter_native_preload', 'test_source_only_unittest_cannot_be_native_pytest', 'test_source_target_loss_refused', 'test_stale_existing_controller_bytes_refused', 'test_stale_provider_bytes_refused', 'test_stale_test_bytes_refused', 'test_static_case_bodies_cannot_be_hidden_as_support', 'test_support_is_not_an_executable_test_target', 'test_typed_fields_do_not_coerce_truthy_values', 'test_unexpected_new_peer_is_not_hidden_by_pending_metadata', 'test_unsupported_role_and_lane_refused', 'test_wrong_core_pin_is_not_repaired_from_another_target')
EXPECTED = {'tests/test_ci_checkout_eol.py': {'role': 'callable', 'lane': 'native-explicit-packet', 'requires': ['exact_source_inputs', 'git_checkout_fixture'], 'requires_sdk_absent': False, 'entry': {'kind': 'callable', 'invocation': 'python -I -B -S tests/test_ci_checkout_eol.py --git EXACT_GIT --fixture-root NEW_OWNED_ROOT', 'callables': {'main': ''}}}, 'tests/test_document_embedding_handoff_source.py': {'role': 'source-only', 'lane': 'source-explicit', 'requires': ['exact_source_inputs', 'source_controller', 'explicit_source_binding'], 'requires_sdk_absent': False, 'entry': {'kind': 'source-controller', 'invocation': 'Existing admitted SOURCE bootstrap with whole bound shipped peer/products -> main()', 'callables': {'main': ''}}}, 'tests/test_document_parser_causal_chain.py': {'role': 'unittest-explicit', 'lane': 'source-explicit', 'requires': ['exact_source_inputs', 'source_stdlib', 'explicit_source_binding'], 'requires_sdk_absent': False, 'entry': {'kind': 'unittest', 'invocation': 'python -I -B -S tests/test_document_parser_causal_chain.py', 'callables': {'packet_suite': '', 'metadata_preflight': ''}}}, 'tests/test_document_parser_pdf_ocr.py': {'role': 'unittest-explicit', 'lane': 'source-explicit', 'requires': ['exact_source_inputs', 'source_stdlib', 'explicit_source_binding'], 'requires_sdk_absent': False, 'entry': {'kind': 'unittest', 'invocation': 'python -I -B -S tests/test_document_parser_pdf_ocr.py', 'callables': {}}}, 'tests/test_document_parser_review_boundaries.py': {'role': 'unittest-explicit', 'lane': 'source-explicit', 'requires': ['exact_source_inputs', 'source_stdlib', 'explicit_source_binding'], 'requires_sdk_absent': False, 'entry': {'kind': 'unittest', 'invocation': 'python -I -B -S tests/test_document_parser_review_boundaries.py', 'callables': {'packet_suite': '', 'metadata_preflight': ''}}}, 'tests/test_document_parser_terminal_veto.py': {'role': 'unittest-explicit', 'lane': 'source-explicit', 'requires': ['exact_source_inputs', 'source_stdlib', 'explicit_source_binding'], 'requires_sdk_absent': False, 'entry': {'kind': 'unittest', 'invocation': 'python -I -B -S tests/test_document_parser_terminal_veto.py', 'callables': {'packet_suite': '', 'metadata_preflight': ''}}}, 'tests/test_document_parser_veto_cleanup.py': {'role': 'unittest-explicit', 'lane': 'source-explicit', 'requires': ['exact_source_inputs', 'source_stdlib', 'explicit_source_binding'], 'requires_sdk_absent': False, 'entry': {'kind': 'unittest', 'invocation': 'python -I -B -S tests/test_document_parser_veto_cleanup.py', 'callables': {'packet_suite': '', 'metadata_preflight': ''}}}, 'tests/test_document_parser_veto_composition.py': {'role': 'unittest-explicit', 'lane': 'source-explicit', 'requires': ['exact_source_inputs', 'source_stdlib', 'explicit_source_binding'], 'requires_sdk_absent': False, 'entry': {'kind': 'unittest', 'invocation': 'python -I -B -S tests/test_document_parser_veto_composition.py', 'callables': {'packet_suite': '', 'metadata_preflight': ''}}}, 'tests/test_document_parser_xlsx_formulas.py': {'role': 'unittest-explicit', 'lane': 'source-explicit', 'requires': ['exact_source_inputs', 'source_stdlib', 'explicit_source_binding'], 'requires_sdk_absent': False, 'entry': {'kind': 'unittest', 'invocation': 'python -I -B -S tests/test_document_parser_xlsx_formulas.py', 'callables': {'packet_suite': '', 'metadata_preflight': ''}}}, 'tests/test_document_parser_xlsx_output_privacy.py': {'role': 'unittest-explicit', 'lane': 'source-explicit', 'requires': ['exact_source_inputs', 'source_stdlib', 'explicit_source_binding'], 'requires_sdk_absent': False, 'entry': {'kind': 'unittest', 'invocation': 'python -I -B -S tests/test_document_parser_xlsx_output_privacy.py', 'callables': {'packet_suite': '', 'metadata_preflight': ''}}}, 'tests/test_document_parser_components.py': {'role': 'pytest', 'lane': 'legacy', 'requires': ['exact_source_inputs', 'native_legacy', 'optional_parser_component'], 'requires_sdk_absent': False, 'entry': {'kind': 'pytest', 'invocation': 'tests/cold_lane_entry.py legacy docs/COLD_LANES.json -> pytest.main(["tests/test_document_parser_components.py"]) via separately admitted recorder', 'callables': {}}}, 'tests/test_document_posix_fd_owner.py': {'role': 'unittest-explicit', 'lane': 'source-explicit', 'requires': ['exact_source_inputs', 'posix_fd_component'], 'requires_sdk_absent': True, 'entry': {'kind': 'unittest', 'invocation': 'Linux/POSIX own /work: DOCUMENT_POSIX_FD_OFFLINE=1 python -B tests/test_document_posix_fd_owner.py', 'callables': {'main': ''}}}, 'tests/test_document_public_options_source.py': {'role': 'source-only', 'lane': 'source-explicit', 'requires': ['exact_source_inputs', 'source_controller', 'explicit_source_binding', 'pinned_external_source_inputs'], 'requires_sdk_absent': False, 'entry': {'kind': 'source-controller', 'invocation': 'Existing admitted SOURCE bootstrap + public_options_baseline_schema.py/public_options_candidate_schema.py exact SCHEMA_PINS -> main()', 'callables': {'main': ''}}}, 'tests/test_document_unit_context_order_source.py': {'role': 'source-only', 'lane': 'source-explicit', 'requires': ['exact_source_inputs', 'source_controller', 'explicit_source_binding', 'pinned_external_source_inputs'], 'requires_sdk_absent': False, 'entry': {'kind': 'source-controller', 'invocation': 'Existing admitted SOURCE bootstrap + d93_document_knowledge_graph.py + 3dc_document_knowledge_graph.py and full shipped XLSX peer -> main()', 'callables': {'main': ''}}}, 'tests/test_document_windows_handle_owner.py': {'role': 'callable', 'lane': 'native-explicit-packet', 'requires': ['exact_source_inputs', 'windows_handle_component'], 'requires_sdk_absent': False, 'entry': {'kind': 'callable', 'invocation': 'python -I -S -B -u tests/test_document_windows_handle_owner.py --owned-root NEWDIR; or --plan FILE with raw plan SHA on stdin', 'callables': {'main': ''}}}, 'tests/test_document_windows_lifetime_source.py': {'role': 'source-only', 'lane': 'source-explicit', 'requires': ['exact_source_inputs', 'source_controller', 'pinned_external_source_inputs'], 'requires_sdk_absent': False, 'entry': {'kind': 'source-controller', 'invocation': 'Existing admitted SOURCE bootstrap with three shipped *.py.txt carriers and bound native test source -> main()', 'callables': {'main': ''}}}, 'tests/test_document_xlsx_identity_source.py': {'role': 'unittest-explicit', 'lane': 'source-explicit', 'requires': ['exact_source_inputs', 'source_controller', 'explicit_source_binding', 'mixed_entry_contracts'], 'requires_sdk_absent': False, 'entry': {'kind': 'unittest', 'invocation': 'Existing admitted SOURCE entry binds DEVTOOLS_* and MEMORY_WIKI_XLSX_IDENTITY_SOURCE_OPT_IN=1; packet_suite().run(original_result)', 'callables': {'packet_suite': '', 'sqlite_suite': ''}}}, 'tests/test_document_xlsx_rematerialization_source.py': {'role': 'unittest-explicit', 'lane': 'source-explicit', 'requires': ['exact_source_inputs', 'source_controller', 'explicit_source_binding', 'mixed_entry_contracts'], 'requires_sdk_absent': False, 'entry': {'kind': 'unittest', 'invocation': 'Existing admitted SOURCE bootstrap binds full shipped peers/products -> main(); separate genuine_suite(fixture_module) only inside unchanged derived_case', 'callables': {'main': '', 'packet_suite': '', 'genuine_suite': 'fixture_module'}}}, 'tests/test_extractor_shared_codex_auth.py': {'role': 'pytest', 'lane': 'legacy', 'requires': ['exact_source_inputs', 'native_legacy', 'protected_fixture_settings'], 'requires_sdk_absent': False, 'entry': {'kind': 'pytest', 'invocation': 'tests/cold_lane_entry.py legacy docs/COLD_LANES.json -> pytest.main(["tests/test_extractor_shared_codex_auth.py"]) via separately admitted recorder', 'callables': {}}}, 'tests/test_extractor_shared_codex_auth_source.py': {'role': 'unittest-explicit', 'lane': 'source-explicit', 'requires': ['exact_source_inputs', 'source_stdlib', 'factory_binding', 'pinned_external_source_inputs'], 'requires_sdk_absent': False, 'entry': {'kind': 'unittest', 'invocation': 'make_suite(inputs, read_bound, scratch, case_started=None) with all nine exact named inputs; original stdlib runner', 'callables': {'make_suite': 'inputs, read_bound, scratch, case_started=None'}}}, 'tests/test_foundation_ci_prerequisites.py': {'role': 'unittest-explicit', 'lane': 'source-explicit', 'requires': ['exact_source_inputs', 'source_stdlib', 'explicit_source_binding', 'mixed_entry_contracts'], 'requires_sdk_absent': True, 'entry': {'kind': 'unittest', 'invocation': 'python -I -B -S tests/test_foundation_ci_prerequisites.py', 'callables': {}}}, 'tests/test_foundation_ci_review_boundaries.py': {'role': 'pytest', 'lane': 'legacy', 'requires': ['exact_source_inputs', 'native_legacy'], 'requires_sdk_absent': False, 'entry': {'kind': 'pytest', 'invocation': 'tests/cold_lane_entry.py legacy docs/COLD_LANES.json -> pytest.main(["tests/test_foundation_ci_review_boundaries.py"]) via separately admitted recorder', 'callables': {}}}, 'tests/test_guard_instruction_qualifiers.py': {'role': 'pytest', 'lane': 'legacy', 'requires': ['exact_source_inputs', 'native_legacy'], 'requires_sdk_absent': False, 'entry': {'kind': 'pytest', 'invocation': 'tests/cold_lane_entry.py legacy docs/COLD_LANES.json -> pytest.main(["tests/test_guard_instruction_qualifiers.py"]) via separately admitted recorder', 'callables': {}}}, 'tests/test_luna_extractor_boundaries.py': {'role': 'unittest-explicit', 'lane': 'source-explicit', 'requires': ['exact_source_inputs', 'source_stdlib'], 'requires_sdk_absent': False, 'entry': {'kind': 'unittest', 'invocation': 'python -I -B -S tests/test_luna_extractor_boundaries.py', 'callables': {'main': ''}}}, 'tests/test_luna_extractor_source_scope.py': {'role': 'unittest-explicit', 'lane': 'source-explicit', 'requires': ['exact_source_inputs', 'source_stdlib', 'pinned_external_source_inputs', 'mixed_entry_contracts'], 'requires_sdk_absent': False, 'entry': {'kind': 'unittest', 'invocation': 'python -I -B -S tests/test_luna_extractor_source_scope.py', 'callables': {'main': ''}}}, 'tests/test_luna_oracle_compat_source.py': {'role': 'unittest-explicit', 'lane': 'source-explicit', 'requires': ['exact_source_inputs', 'source_stdlib', 'pinned_external_source_inputs'], 'requires_sdk_absent': True, 'entry': {'kind': 'unittest', 'invocation': 'python -I -B -S tests/test_luna_oracle_compat_source.py', 'callables': {'main': ''}}}, 'tests/test_recent_changes_visibility_source.py': {'role': 'unittest-explicit', 'lane': 'source-explicit', 'requires': ['exact_source_inputs', 'source_stdlib', 'own_sqlite_source', 'pinned_external_source_inputs'], 'requires_sdk_absent': False, 'entry': {'kind': 'unittest', 'invocation': 'Explicit stdlib suite/main block with SOURCE_CARRIER under admitted SOURCE entry, or direct -I -B -S with RECENT_CHANGES_TEST_ROOT own directory', 'callables': {}}}, 'tests/test_review_queue_owner.py': {'role': 'pytest', 'lane': 'strict', 'requires': ['exact_source_inputs', 'native_strict', 'protected_fixture_settings'], 'requires_sdk_absent': False, 'entry': {'kind': 'pytest', 'invocation': 'tests/cold_lane_entry.py strict docs/COLD_LANES.json -> pytest.main(["tests/test_review_queue_owner.py"]) via separately admitted recorder', 'callables': {}}}, 'tests/test_secret_metadata_owner.py': {'role': 'unittest-explicit', 'lane': 'source-explicit', 'requires': ['exact_source_inputs', 'source_stdlib', 'factory_binding', 'pinned_external_source_inputs'], 'requires_sdk_absent': False, 'entry': {'kind': 'unittest', 'invocation': 'make_suite(raw, source, scratch, case_names) with exact owning provider source/carrier and explicit full24 roster; direct main --source FILE', 'callables': {'make_suite': 'raw, source, scratch, case_names', 'main': ''}}}, 'tests/test_source_suite_stdout_bound.py': {'role': 'pytest', 'lane': 'legacy', 'requires': ['exact_source_inputs', 'native_legacy'], 'requires_sdk_absent': False, 'entry': {'kind': 'pytest', 'invocation': 'tests/cold_lane_entry.py legacy docs/COLD_LANES.json -> pytest.main(["tests/test_source_suite_stdout_bound.py"]) via separately admitted recorder', 'callables': {}}}, 'tests/test_spreadsheet_formulas_bounded.py': {'role': 'pytest', 'lane': 'legacy', 'requires': ['exact_source_inputs', 'native_legacy'], 'requires_sdk_absent': False, 'entry': {'kind': 'pytest', 'invocation': 'tests/cold_lane_entry.py legacy docs/COLD_LANES.json -> pytest.main(["tests/test_spreadsheet_formulas_bounded.py"]) via separately admitted recorder', 'callables': {}}}, 'tests/test_tool_schema_source_parity.py': {'role': 'pytest', 'lane': 'legacy', 'requires': ['exact_source_inputs', 'native_legacy'], 'requires_sdk_absent': False, 'entry': {'kind': 'pytest', 'invocation': 'tests/cold_lane_entry.py legacy docs/COLD_LANES.json -> pytest.main(["tests/test_tool_schema_source_parity.py"]) via separately admitted recorder', 'callables': {}}}, 'tests/test_cold_lane_current_composition.py': {'role': 'unittest-explicit', 'lane': 'source-explicit', 'requires': ['exact_source_inputs', 'source_stdlib', 'explicit_source_binding'], 'requires_sdk_absent': True, 'entry': {'kind': 'unittest', 'invocation': 'python -I -B -S tests/test_cold_lane_current_composition.py (own TMPDIR; full old41 plus current composition controls)', 'callables': {'main': ''}}}}
BASELINE_STALE = ('tests/conftest.py', 'tests/test_audit_package_contracts_20261003.py', 'tests/test_http_redirect_safety.py', 'tests/test_mandatory_redactor_admin.py', 'tests/test_memory_diff_polarity.py', 'tests/test_observation_finite_work.py', 'tests/test_p2_g3_native.py', 'tests/test_p2_g4_identity_errors.py', 'tests/test_p2_g4_repair01.py', 'tests/test_prefetch_current_diagnostics.py', 'tests/test_session_extractor_codex.py', 'tests/test_session_extractor_grounding.py', '__init__.py', 'packaging/run_native_regressions.py', 'scripts/ci_owned/ci_child.py', 'scripts/ci_owned/memory_wiki_ci.py')
BASELINE_B85 = (
    'c-ri}+m0hwmZo`MPhp6gN_7S0c0Nc`4Jac*nUN)hl!{Otx~o8JGu!4)1)XH_5Ql6u(A5_`7|Z|#4CX=lViKsCM%BE6^a}kX^R2zN8R_9PlCDxn'
    '4AQeIBO}~tByHJVd#}U4{{KJyndd!NR9E_1J@~|XaILSW^S6V=QdKWMu2%E8o-7B8>1tl-K{XxMgRz?E#l@@O!9#Q5QY}{tx$yZ{-+uGx$?(x{'
    'pFH}jufKZw?8WfeSN!+07f=8C$?&tsUp{^Q{OMQE>{ZQt`bRw(&gRosqgv00iz^i-sk}>6CQ*=As!?fJt2&JG%vZXqlOQRTpXF&1=T(^aVO7_8'
    '=!aobq<#@qK^lie(p2{SCtBBwVKbVj@o=uo(WK_R8#P{N^Xt)MwptEHlULjuH@oriDphq>HbI>yg^mIhsLaocAgq%*QGS$0QCuZu6e<;mRT|fI'
    'm=#%Fq)C~ESs3Q_<Hb&LbCq5!v>4|<@l#{0`KVfU|K=yZee%thPo58-KY8@+H&0*u-SGK~Z=ODSA>YK>*Su({=9hXY@ADtskK~7Xv0PlppTkOx'
    '$0d(zI8n>dD?J>K8oeA{>yKw|yEl2~im@795B24oFNlF&sqv`h+UaEPCD)~{>(S)WUA*J<(^}u{6Y6l-1iW^_ir^D=ypZ3&(zW|a*J{bXdH+A|'
    'd;e**y5@=B@msZ5IpbE->+8{S*yu^654eh@HRr3&c_4EwKk2_l&qfPlw1aKjOy_!ZIpN(|;rh)`)z_oNV(0B#j;AF~arL&GkLuw<t9f;`<JEID'
    'yBg{@%ekt=OnbkPd*AtLA`6f&R_W1fx#NQI_<A^#wR@+Ba;@=*_UjL8p38hOTE5+J0frq9r>mtn{^d%|<&l_A<a2g>z1eiJ98K8d#^behhjZRY'
    '@49NP@j$+r+duh+>T)7)RqecL+Kk3}c%{{NiPb0dY&x3kU21=*=ZaU&R^@n9se_&pkA)i&51LMvW|b<w@7rA$@EI@NhB}?&fc>wvXN5e-k$x?g'
    '$Wq?%Wmc0>GcqnBU#jzh>FbI86nD`-blYLYs^8c{Wna}}T`kRfyc)?9;@6Yac)am})A{IfwB_d*YC5)?$#k(YZ!E8HFZj>vJ$Sw{o7%e{ZOzV>'
    'G?qp9cG&kh-4V0-?tixN84t$#QdMscI~@Fj4u@)FtXN-Q+Nt?=m0I+y+wQgInK(z;y`Nm^@eIFnThZvv67#K(bo2ZcSEJefYu(Oje>PmOT*i8N'
    '$cMTM%|{K(>1tA|`Kadx`!8f~p1(c#8g@cGT(a@hT)p+Gxt^)fd>99c|D<mJQLJ+7No*-28+BCEncmoj4t_JUUmDkabK?!ozIO1tyz@=uy!jE|'
    '#RiUir8)cWt-I^@dR4KZzUFLf53e0BT~4oYG0vdL!X87rUc26a=dy3&*P|UTU)7xDB@2grmpiFmvL1*k)4=zmeV6eB8hn4bIQWX1E$;2XueQh3'
    '-Cn)W969nNHcp&_-@>hM&K%Z(JxLC|RF<T=)MiymtZ?{;x^15@sn!!&goj@^)@)}(J)chxd1w+LU(RKd7=AY`+c?g=$DtSPIK@g9+tsz2zcf3b'
    'o~WH?wvAlX>dk08QaH<ufR@dFZ}e?VJztK@!?{w6t33g@`=DyM;^4MN#X(oFg%iQ;3JJEnSf2iZuy?+=+hsOX*mI2yMY-mBHYH}M-nxBZ|Ch8^'
    'PNu`r^=vE`42hUVlY_3B>1)1Ty>HvuyrPZ$_H2L~m)L_qcEmj!@U06cYPPtVE=|T)y{*RkKCcS|WDPak)$pZ$YXa$NzISEZzW7kfEUrlCWNVe='
    ';8Gv@YN;(~j?U_8G||IGt;TYYl0(1Q^$wE>u^>A_mx9&P>phRVy<|MC#7z!4Xk?=sO;&c7G+*1rA8!x7#-88%FROLAy5zfE;`+<019DDDir7!a'
    '2QR7hm8<2{=AW#56SyCG(RW1sk{nc1Y9D=((U$An+Gl^APp7*Q#qP3dJ|$1I*YO4U-61Le<~{9AcWz#0Q*nuE4@>#2Z`!qFk1B#=eaNkiCgt>v'
    'T@i=Boa)E5$;*tp9CVq~3YM~w&bf?qYkX)8#M-;tcMiB>I(>6JCSS*p_}7Rd_kfGKOn6ES;V$3r4=dT9Tn5^1Q-_$c+uJS!7X}@2k*jjBkgulm'
    '(LpO}QK`w{PuRTL8NJ;ohO^+HEA5$5?JNYWUv3V7^@ffmr^|!ZtSfNYBmIDLXnkROcpb0<cGs}PIS5P+bkJ64kC3}O)XtsmauGEQNh9i=;nlWR'
    'OKnXGp7jBjy~c5;uNNkIHJ-G%!$nwnZml+?zNQYkbUK$)_<*8f?<G8|(b$w$4!c8pdCA`Sk~L+@^oL)jC$H{c7kAB@k*OO^r+4_EX1rQZ+f%c{'
    'FS(0jbeBw4Z*a^z+MYO<5LCa>)#2B;a*uJu!>^(!Xls1jmYS?)=3!F<y30Gbt$LxCt2<b8wQTYOUM(lj!AJccN3**gQ*z04cHq$@FE;LX*oWAF'
    'WwBh92Sk4BFvT8#6(RGE$KcYgcZ>T6USK|AUl)UVP1AOzIL%9a$OTjlFxP0;$=JQvwkZ#Ip($CpVEd4lyY%gVmo6xLVVLTWm)d1c6@9VOLG&wk'
    '>W?MelG6O{=klh~X8j%3VA$y6IL{pi!*O_*3)=e9j-He`Jmn7LP&dV-T}?0h@{JE_D@Z#oVV!h!uCDO7Kg(&Tyi=biDbih+Vb9vU94)W#z&4<)'
    ')oi(|_2HUpuWU9c*_SM*(RlYo(<$|CY7$a=JNT2V?>3w&%Y)i}o4!7sn~e3%zL($Zcpma8rUqFnIrr(c4^1(6X9RUMHQhY%WuD<RG5G#k*wu15'
    'lSq|@YPG+0MVH?;6m{1fIyf)xl3J+@+h$z1pEob}HNv)BZS87O4YjKdvgOjQgK$ttwe1b`QVp@iYFAjl<+?6ucH7->HCyQU@=otznkIMq;?wzj'
    'HCt}J$(^q6p40Ve=?X60JMF*PWS?Dq(rg^SNLHiq0iQgY;4m{fSa-Z**(u$vvja}Y2RtQGy!pE~cSu>ZyM8{q!dX?bl&JPDU)EW}^v8#b*9wQ6'
    '+T;F^YhA8Q*eL}Jx%>`Sty?>`@_#@Pa{V5&F%1|~cv{z!b_YxETx&{wT>*5du4jjA0h<?_O!-G#(tYaPu5~-VM2J7;LQ`Wp_(HcQo9kQ0TO59M'
    '_efZkg73KFlDzpQce~}AMYSJu*;tCyKk`FOok!YW_WWP`$aesRpqKhbUOc0m^<%Cz-}vC`s5&m)0=t`~f6Q8t2AT8GA9X!h7mb`d`&|pis%58|'
    'AM$w%J+YC}-S@QhrAtch?)p33>}q1aw<^bXJhIy2k~z8@-cbtQFAu<b?G5vIpXv2<e<<u;cVI+6o=z@_H??Vx?0@U^i)|HF&e}VC!mDuqhe&g3'
    'X&c4|BtO^HOagLN=BT83Y@4nJTyyZck{7#}nU|C7FHDVhS1VI4`ED_t%x9JToW<_fPNq1N!>TQ8@8_`Z)%FFX8nWjzT6BO!y#)Vi&#PS}-^2o@'
    'b+iA=IOL1H1SBS%$va#??!n{R-BEIRQ9WuJ0<E#yop`%fn-aoe@5=x)==rOC2egGvviV5@Ajy+kb0kpvF6!d$L+}tc;F%4P<n;Awb{Il)<3^~d'
    'j{%atnT>W;hBhx~yL$3bz2K=^S5dQ|YHW&;hh1QSQ~r*=&D4eutk(H%jA%H#jP~{=HsDWd>l;T?rlc&ro<rcPYk<lg>vUIiI7r#!4}g^2yxO_p'
    '0k3rZsx=7i4xh4|E+zMA@umA-ZF1MWr<Hp_TjFz}z<#i=L+>8Y<a9{W${ljwnaa;DKb*a#Ejbx3>X!$=dH$f<j+88u?^Ziu8tzLw7>|LA9a@BI'
    '(aP%Wc&h5%H}D5QOY*)QwrU4J*^dnR$hzDv-*9-dh6xc<oj#y5<1XQWPIj)DZ2+0e(PBA&dzWh#Z?D-4ULMdEU0-VvlKUfp_EbFlm75*n)jLml'
    'vH$Y@$FGByyJK`^@%0BRBwHl61#_V6mpdWp?&RH!n|8fgTIXiSq}{#`xMOowy|HD^iH!HYe6zE%_r>k=-upt=G;}+Dy{pgUMku;w&H9kvb<K^<'
    'w|&NxVmTN0j^Vs>b-NKBumg4=1?yDZrD7C-W%}?dUsKm7+8A2Qy@B=byx6Y%4uNslf@tfdn^4?+)#~=i9bBoueSw9m?u2gLzKCTrF;gw`{a4w-'
    'kcEm(2v@Flk2N`fh-vCC_KuBoV7y%~1<1OTe)H014+k~BI=s_jC76D9FCCcn(D{^u=UCcEsQ&_7O;EY}k!7#1v>vy!I*a3<iMiC1l|-|O5ZDIS'
    'e^^l%lo?De(L1JJ2JII2GmXLgqIUeV_D^Gj2i;Qa?xC}Q<hyde_I_@F_1%cdR{Z;V=;%RQ7oo1oTBl{$)J3J!y6{zA#%UbKWur0`)^(DlMdGJv'
    'mSj2z%P3>$RToWCg&T&Z&M!Ce05`&)mg`^0T=3RkuxQN#-L%dFw<g|sVET=Tfb3Ra;6IB^pKxz2+0vG0*S@8Rc+J{dZchDLOKOZIpSgLNS{S20'
    'cz%uJKJ=zdBgvTe{P$mw=6P<iY4NEyA=;RGCbF;i_2a+trgP7M|Lm#faTZ=p0Wf&a?N_~US6>(-c;vaOv3}@L0r8Y4kJFR2`0;~HU+8)4B`=ik'
    'HQ2dRZaniUO7lD}!lcw;prVj@>bxj)nMHn9RZUvxhSiWojbBw+6V@41&skjQrqFR*1Y4f@6{jcn%Kmoyv2Xj`Pxs{4@BZE%z6qTkdbIECpspHw'
    '0?v~{r!%?dYIzG!LM2^$<y)_fkG-xw__6mj--ASi7p%XwXYPqLG&PTX;V~m_H<p7Qez%8}cAoO~B;Uq^5B(~RgQD?M9Y%G<41G`}IS!vBd7gxg'
    '(zPE|I>EnHU8SiG;wUPEJl6rk?p1U9!3$zhzQ};$iW#BU;`Wvz;PwmJMX<4_zO)1R-P>+HX=;zI{3frkIjlE$>J5JF4W4_4T0^#SoLNfRX8!&^'
    '-#Wa0+y>;}YRh^&D&NN<d^=fQF)ChpZgTo!tX3qyp2IM(--yi?54~qk{`$!`o;?J-C*c#X3nRQI?h$zQYkG?n+nC*eKD9d!p&QjoKE+*+m1Qfk'
    'D7-r@$9Gu)+;-P@3MD05OkUPO3{^u~1Qq*J8LKKQ3niPBDvLBo(^!RZsdSSyC5#V|DkI1q{7RqPDbyRPygL@ZVb?96*exFxh^`0bp?LBkpRkVD'
    'du&_Qd;ay)3wx+NbjKE3RJ+G{zkTuIYftX!eH>ov1!K28i&<OP2HUQ^tW-@9lpIGnyIIrtQIv;ymBezGsWNMtgmcUf@;It9m87*wiztAngLuZT'
    '^Emr(_OgR4^X|UZ{a9{rHEGw0e4Ko-hu*(?=-In@=n2UAL3hCs?udQk*Bh4EOqO;y!eg6!vAlonNn4by=@U=CvoE$!%##kB*P?DbGD>zrqH!Q&'
    '<F{UGZqE);wtJ;aIuox?F1z^fWA7VxvtA1T^30QU55S`yOonaWznaVQ{nV5Cg=Z1LGAmCw!R6v$0^lYc_cWCXf==s!Z2zVv+PrOdZi3Le`k$@*'
    '?R2^#^J5xveo;1wu9`U14RJ!4kS~;VTsLtO*I7}MAwatm<;vGZl2A^~%F<72zxj}yuFo7FY6P)leJOg-x?Sexjz9GvWAeT<y+7}7MlVP00@@h%'
    '{)Iw_ooqgP0t%JpX|40Ls>8I%f+9=nATNus&Z)Ddx`>Er%e;<#6~tMtRg>mA)>){7BnVmM=Mzx8OMY}%K=IfH4z8fH5kPotdHj`0jHjLec^`VF'
    'k1N|0rP-y)Ze(9=Mwjn3rr_QjPEJt=2J5pkIjRCbYYKS7qB5+Tl(mqiLBkSiO4d*27Y#*_O4V_esxl74kYKd&2{Twhlt#8J8M|?rr}vZWY8~5}'
    'Ig!SC-oL%o`jwn-oRw-mv7>$-aey}%So_}DQtx-$+qk9o6e`I5Nc`kVZaZmR?2Eer#$L?R&DXaBf_q%&t7lKV#pumI%JDPLlH++2(rf(0Rt(kn'
    '!i+z3p@r%2nutR<6ujpy3hA!42&=Xb)$Y9X+GwTT*=72+gDpN2WK}?=s7lMEU~|<`ld352W51w$7^GV1tSZZZDuXKOST|MBRKx@-ZK^7c{PH}i'
    'hmXQfx}DNyT!WSk>EdQB(UbnuItAmGCMuK+?7eQ3=B;+_j<VMkg`!$q#A)b9q~(#Hlwna(T`ud4jZo{n@F@>AQIoTU7UW+l4GKz#s>qKx@*7m%'
    '-#-{h6KE-0<m~Ok#any{DoS!?>?LuI`}NoS^HUph|E2u>SG@9L8Vs*Ko=s=J3O@SiV;0DCOnm;Uk3RL}mu5b1B>02nul$Gf7=LB1=I6ry_7Sf#'
    'ANjH5XfyMU?Mps-C_kI1YyFphJ~Uv!;qcEt`uhjoVbAW?e!cOFQWzBoZ)fjjigGJAT*odNW3Y{PHa{Iaz4en{-}=e(TR*AZ{mF-7`FFqf?#Hn4'
    '+JD%*(0Jg`l_zg|;)9#7Wm~yRsdw{4b=%ynhk2LxGW@S|;c47Rj7BYi>4C5A7TY1OcOb;qBqGCVw9}9+u^iLgVxuqrX87po@Y`okUkpEg`nNB>'
    '{pQK@_gvH1++YkwL4pOWqh(UvJ>d5gwBLGaJK~K;PY2JwdiM1f-~Q(5v%!;RFTVM^fggP0{qSGD|I_#X{rms%!~gO9zx?pOfBz?`f^agKUGhQ@'
    'O%J{A|K<CCl|TO3`~F|Q|G&Tg=kNc;6OWT0{mJ|OpMUtr@Bcr3@jtl!pT7Uo5C8RtfBfN}e%=i6HZkg+aHXWb6-u>GhnXB#X~ij4Wb{3vAn}_t'
    'E32d`vofIP6{xT(f+X?zYaOY$D&zCX3U`$6cPzCh_IY$+sVOwKkq@*8CTx)w8PzTNsbq~0yBNpeBfT|e%6koX-i&rvx+KeMQYr{plvjR|g@rW0'
    ';;1YWiq3IeDH;;G@^d=jL0ZEDtrgtRO_XIh5zl?R^Zw$Ut&i?L-1(Wqof}W#KH9mDc8(_6`SsIhj|Wfw_UQ`~=PbI;IeZ(kB^oARQ<`+~$Fvm4'
    '{K8cyEj9no8^^p$*S`B;qJZMZ6j=~J$SGe(C5d*@#7SP2Aux@YBT6MvLTe_inkvr&o#ZsmeHt=oBYY5LO1CK826&*g*ax*1+|A<R^RK>n^7J>)'
    'hWz>L@sqz@t4w@+UH|+Q&7ZN$^V#Fy4ctu+oDuK>PuR{_s8|kWW$`5wauJzPtgl);TMO4Fte#d^7c*hfFdpL>5&`Qo4%}v`=(}!X7qnftisjee'
    'z7S`cHsVP9%yd4bph#6~u3mSzDZYg~M4^%ptW?F!>S|#jQ46nyhu+PZZb=jD$qA@YQN#4XK$U(~)5+9{@5ixLl)3_10y<4pSr<jE!lo$$$q4|>'
    'sVpH|s0(%9DcZdu|K>*FbF))q9#mWT{PafE^Fk_~4_!H1I!K<JtM4@<*a58B23R6rq~8r{lEz^b*Ypj;C~JZ|%v6)<l7A-+YpTk^v@ZQ34#_c_'
    'SZbnv7*xUis`>F`xH}fx7hilikcVhePw=`PN53cd2@srXL}s_-?0$A(nv)j`;THTE7TOkBj@@fb*Hu-iAW17f4MAQ+Iu1C^V?a)Rm<L%I=RsZS'
    'ggS;F#=0yj6p086;<EB1KRBbcwzD3zW7+)PJQ8o?k!+SQ?DKxj*SoOC-Gzlqe5odIHO<>|?maG<ewmJqWkR_Etai?gM`@|@Fv$wkvN8^^C~s5{'
    '#Y#0Xf?1$<!Yod;4vI9(qXN+?1^~h>fH)h_-d-h6kmQh1@SV4~75}*#6<I8K_o2&K-+J~lY&7@it1li8zxeFgljk1`n}9d?_b%4{Sd!IW{l~xG'
    'Yp=h5@DCq(uSSX@=V)QTSwdR26c~cMR_MCkcUag;a9P{^^pW2SF@Xu<z4rD!X?NSfKp<#DWo@EjH5t}N?!%2N$sNvSNYQ)b0Coa%L!)A>EFegV'
    '7HkO8VK(0zo)MJaBuk^IDdArUxgmHpffhNun!&_(!fJP0{`OdKib-Ohtx5Lg=^SS@$xo6p(GsLVmivC0)rqev9D|_;_*YaD)f~`q9#w3S<W#CD'
    'b*!?Y@V5;({9?ts_7xw?cZTO)9`hG;^_j<$=DvCApHo2k((E(8vfIr^wvXK58XtZ3%{Na$h5t$l1_sJ28<J;9Q$PB7k!?3V%wkP`n)1QcYJmL&'
    'gXnCR{U>tk0(mtEB(d#7lhripr8Y$X=Ov3(`3sc;_9`uHEOh|#zK%gPCq+oloxTPD%q)!>#&sC!D3d(Y+V{~c41r$MS&VdI3?Pn)FkKfqKcQW}'
    '&unL~`BU|3DU;g;+QOD?=-~pFHhU+d;_ih6ezp_}kT!<-W%v7A>tQPpr2xZO#f{DqMw2vXleh|!I;sj9GZeTOZfoMSU>|2zjgY7gk}3})Uf$5c'
    'Q|b9c!v{>Yu2<04LPaw-u*@-kT*2Y!IRLJ0Q1G_qr>4**587>WZVqYfaPK1!b{loil1MZXumF(~%Ar{lRbb8%pM$+ZDz+(;SjQz;vnGfO#YC$g'
    ')?opFDJoHjtur>ylV1`oPO;PAyTNU;YgL#H*G82c4}+8uJtw|1SO6Lj&aN8}a;q-kK}|KP-b)|19j)Mwge_h6R!cF=?vVHZ5BoO{^Xn!G;xrG!'
    'prJ6HCUr$hq)J|tL`+DgEDwr;8P#;8e5v-akK|Rv@bh_1zB<KcX-|2^yx#x(FaMYKdTs%WbN$*(MN>BcmhTyu?3_JgX(w_Xdaick-C+NCA2YD+'
    '^8PXN?=^MYBH_?T^FqZ@LRLV~6qZ5A1T0uqRG-;0Y5<Kf(=0Js&N4KO{xdb1f@9@={{0u9e?J7`y@~U$i<*8}m?uQTX<CEdr%e{?)XyS<hAb)>'
    'C6wVNm6S!$=rF7pX9~ke_6V)d1GD_34V7IT?6c=DJWF^nr5<L4&;%nUah{{h@k)KAUX6rF#j`ZMKf}ZBh3Ie2tf?XZn-l7!4gl}?u|ljpp&B2t'
    '3<~DnE2P@1Dq?aiX;PnA(cF(yV9gn=)Mi_TbfVG0Hvic*$1rJuUb!dFK~{^IY53Ut%r*hrpGrf=s<&T!_UMa?FF$*9VUClZVS#MUWNeEZ<20#K'
    'AX`nKYuYk#$g^j|&x$mqe#-1mpfgrMUNJ-l?5jvwKso0`Mstvi`>fZ-UB_qk%*42zrhQ^=BnH@$UM;j~<aGJF`w|y+iuUGl^j_E0_Icwi3oDXt'
    'Oj$M5VCtq;z%=TB!5EOG6+cblJk7yx=sKiD2mue-X+SBShN6tqYQH{<L*{Em#z+deHmkS6*k#g;8;{*p)a3r8+VCq^>5y;t(ffVuJJZjABO_K&'
    'SOiH?<{G2`L|?EC)MeeU00KxX7>*8#x~6Oq5KRIvhFOQFt@E-foBQ;$H~n-Aq*Yb#29eF$Fj?u6EW#7>{5j+C`n9)a;Ipa3`&<`}B+&7?E&ebT'
    '^4|mV4j@{7h~t-3vV3^AGU#~Hi0M+Yki5wXCEG%sF)bG<RZF)n1EU_WxT-A9<I^u=9h}U0cTNL$thg7W$y-B>G7wyPo8g${=4#XSX?vZXxm`j6'
    'BOtbsrU84^a<zQF(XTo9hRqfd&&_=)Cc}a1D@X`ebP_74b3#ooET`j@=8>O=3cMhVfjnc;DWUz!!=h=3dlRCa^GIzuSjKuFA%=}6YHeY<a`>1u'
    'N8s3IyK&jCc@pmNO}ww3OMRmj!HW0zytnV1+o;{bs>};AnLG=_obmObpeWvCp-Rh$vnGpuaRbU=IWST}6aG^8c~1QtVjP{F#WVlh4ci)~Z^N!4'
    '&$n%$K=e{s+@Z8EBmkLj_Rigtc%M((>EBtvclYSKZ`;=i46~r2WGU0wk!olI(i?#QiBao7H9Tb&MohP)tn$VWsu~<x7*`<I*a|=moj@n>aQmG>'
    'OYoU%&$JuHW@Kcw4%dL*g>b_R7#@+j9llUuhu=K<h1-EQp5~3ye7G>1_OiDrE@d0Y2Z|D^ub?D&ihK?=_Cx{z3D$u^1z{9&$c1Uif0$_}`ET+X'
    'nj&gN#fiB>zwu7Y4~`>-G*Byh&7kXnv_@~i&&~zyL1DHg+hyxg9hbcvoeP@p+Tw9Xy=X+gqW=z`Qq%;#A`{NS9KI#eoF-9Z%YGb2fTW2-=%*+`'
    '(g=#t04G$;t@wG8pQa0LG2Yo6MHhzBu3i3J=(RS6IgT1tN=r~~zdgC-P~x(q^#ue3deJI5l*!BsHxMdk5kM53rVIoGpb|;GLX~A1<0QI@8U{{$'
    'tyKlNDL@8AcS3rS^(nhSYq#?W#@4Ie-206<Y-|c$S6ow@Fia{6od<LQ+7UW|kwI#Yt-hYC%Cm^>NmDgN1?zO4M@%JFS|xd!HUwwVRsortDCVkE'
    'CKU@9r6^8>0CU6YL{EcvEqCJ4SdVDNzDUYwm-0vkVlKmh=1~@A%w1N!Hyf{nnbl*tUk}FM5XS2e%DUGt>@rs3Z5YF0tyJ17J37g3A&cc>WeD7g'
    '3vCxT+AQjU*^Qbc%X~v#se!enuo^>U8N_Hg#PD4*=0V-KrrOiMUQ)~H6Xsb-l{qWQ58spi4F)|2B(NQm=!V`b2Hi^W9-kwafy=d4U-#^8sS0i)'
    'wwP7&mGE>zMwiE&4prt?A#MOnCnKq7A}GO0G9<q*0?F(ZNY6Y3%13J@I86`OXUP*kTeg|xoxR|;=;SUMi4V$+_TK5XPC=S!KW(5rW}dyOBZl8A'
    'h-?FpkK`YOXQb$`cqYt~<Yfvx4op2YW9Cehcvg6tZnV#m_b14aEq$lpI8#o7^5*g1Hy?;9M8!w|h|e$*#gQ1r2+22yl)@rHUWDbYN;uzQ=3|o#'
    '&WAh=aTTROfcgGuuKm5HykGpk;Nmxrh<s+Kpm5PG`Ask86+${+aEmdxR)$>AM2Q&yY+wg~o|oJj)T=_ijh#M;@+5)HqCwQHfdoASDe&Ph@LqGB'
    '!6N>~-YorRi^24)?vG4c=nk$e!k(50XljH+L?jt{j5#<ei6M_-wOjRK1H-UfKD`VXFz`3X*D>Zw?>kDX+=meZuw4-66j-AYtff#jg0~B56z|eP'
    '!RrWDW6FSsj!$K|Z?o4KtoJXOiysYG&`z$zE_c|g%p}n@cPj-|A>%Uoe3Xy8>3WPsX2XwTwXgN%=SCj28jpHaI|)Ssil%TDkkm%H48aY9AOy+<'
    'DNIo_y^!b(C^1r3X$UHnd8R7KAZcgJCC*M}!EZO&(XIK7UvvT}9YO_$0QruK_uv`7own1PYa4miYSvX=YCT&xb(V@AgJ=nAAz-7vif1fGV^8F5'
    '_3NYX5Yv<|=@+8yZ8+)ZBJIK1risoQibFbynC&ST1IlwHUAYvLR08BSQcMCfEiT=N3e+53I%dY}0BUH4%TFc}+GDzVkJ%h`?1*tLqy``p@GTHn'
    'e95%yI%*KttK*rh#30AxCo;9b{Pl7#6ur!o5*9l@6WUM^p(rOpErx0$8E_KTDT#8LGX5;}Ri;^TxX_uQ%Ty4+EQO-%Nx8^YtDQs6;0G7q_@UDU'
    'byPVIH`D}00C`|1!d>Ll`a#>G2Ks(Ht6yet-tJrZMTY8ZS&<i@YM9HKXX2k!m_iWafB{5%$a`fCXj-bD$bdy?&oa)#KvxKiP=_bA@^4w}3|9T;'
    'P(lhN?dN`Y@wp%I-*^KjyYN<m+p{ilW7g0~tjlYTXUSUzj6F-<utOJ&Cjz#kKvV!gg7=~dL<2mcv0Ri@N?)KVQ=sCJjD^6mQx;{am>P+q;-r@R'
    'EsLGQl7|j@bBVW8mX5gDn8cz|%}>Qnl!Qv*17w%)hHQ^((Jy!>Q?=fhAKmK-+GkQCC>eoa>BkKUXZQe&FVv8#q6|=dtb)`Bm0G~5iST2>R1F9V'
    '#O-qQ?(!4#gnec_<}BfQ^hR&ofuyvH_tzk33CzbloAH3_$ELF6-d<RSfp*Ixho+Kfl77pWx6m7uYsce4&ZHZHzx!M#puXxuiJ+k)MlY!j^9b54'
    '$gM+xB*CZ^g#yS(vQpHQ0z?6!WkXUaBf(}a{<M<n-R8TWuy_v>7Ed=M16+pk`ihk_u+w+9&bR;Y^lMHoLo&J`)(ZxM&;9gx9MEN3!)~T{@6lDK'
    '33L*90DuDsZ3V?0ELKs<A8<|Nzyl+?)m2ym>wpxRSqo6-63zidr|y-Vl>hCt-u;QyV$VA+=#ClGVrOajUFyN5GRFDbPcB>~K;~g*ID<ZlNu-VE'
    '?dTThY}TfOxz}0ZEYl2Lgm?+1-Y5^@$SpXa;;=;SFPCxmluV~U8eSp$kwv;;Fy7}3gJ*ObVdw|!EW3<%7RgUSj-TE*AcQHT9rAX2iP5ET2g`5a'
    'BVzed0XrraFwx{t&*#&<9S~G50fgsFQq-jLZ~{~nz45Z3*TFHtaS?;^g8`t1C4xDmfbKZtn9>_Z$OQJQ6I=g1mb;JB-b0+`jvl<ubA}%n!*BXu'
    'r@~?s?+35cSbC7tj!sf?sblaw$?t^TZc-1wo0db1D;S!a>T$dVxeX?mC>aaJj>&Q$guu}g5l=7Ca|z*RfNzwE4HOA7I9PN{yS}8E&tykjol13i'
    'x8crV=BW}*8Y@dis|111C4Km}4z43gw|l0bLU^yF=79OyQ|ZxHUw(;{L&v%;r&uerD|5C3v3ggpK0g0h^dh-p3J8=JR9HgFAjFG#sxl6&G-khn'
    'mncaUip;UfYf>Lt`YFtMv5qPoLW~uhq|Yqw6B#k{<JDYl$?{6$4$U07N6|2OxE`#1=#{JbQcLwsVmLE9sOz>`*HY9Tg+H(dTwSaAOT$p3C#s)J'
    'Qo&(T(}(n#W1_eQgF>7!AzoIM;CLAsPe}Y3h+;N_mnb^(WhUa(Xjo@L7<Vd8vE5?#(3MWYp|wia)G>?si|OPNcK#=XR-R&Pwh=wf>y?NqYNN|3'
    'K4RRZQ6op>ULS*tRIaSvMxVlEv>aXca<2M_oxvZGMKzIDs-h^S?p#L-RS*O|i6tTX$tpZ1V7i0B56JOiyeN&r0CEz2xSQCb{`++k`x!sNO?FuA'
    'cwEI<@I3@uo!+GTBo}WsEm`l5K<jtkd^LDP_3KfGgArF@$zFW<%~xJ)S2<KhrjQ20d}?XrEGe;86JftT0>>Gxi2{ej52Cj)@58{9aS|0k<xA}s'
    'RRb|GoN(x;0hNygR$rx6#ULOoq-8~tlIKN*7_N#NVbiMPpF>Z2ze*b3a3y~6)EoTT8$9>!VvC<e_3S5>_}M~8>>a{d{BNh^bu8T*3H&FXv4q#!'
    ')~(}*tq_$QEXJ9ZlKRXMaWxr=@S}?45P0KGY|~;YTRn-6aZ!uX-5plH!2hZDycvy0d>YZh=oRO3A8lez63%Rhk9rX8l(Ilwy#WsvBAkxwho8n2'
    '%bL1@R}(5{l9L9S=PU_@Efo^yQ|YDj8|@6r!k@Lb-D#kA;gIlzZjzD%k{4`@IL}D9Jpl>xaR}fXMTf*bMQz(+gnFhMeWeyxy(Owzhh-{afKf@T'
    '1Ug<7%)63fBxq=%hf~Eg`T+-*AjA;TlrceA-NF<OQIwKSYVmJ3+c^xqZp=$TOoe@9nNKH1n&}nmwZuD?EJ(A|`HM}htx|&+rQ%=pYSxM;ACV_m'
    '&2dIpY*~5N2qD4@k*Fi53{*j+%SxB<ho%UKce)~t$`c(WVC8WQz`}U~Uuey+NL(Nrb27=p4zrzj_Hc+|{VoZU`RLN<mKYNbgvZTm?7USqpQ46m'
    'rRdE(F3Vp{UV5k`)v$^mk-K!d>Gsz9I*J5Dv?>(JSRpuK1k+GLi}C^_3Yg+JV;V7!0G}jCE2C!+B?`qf26V}>{iH6{Y5B@+o1KfJyla5N9K{9u'
    'HJ@KC2U34x7#ASdjg(^AdXpJiuLo|VxBaM1xzQtV9_jD60NS9ahf4*hX4$I^q@>XYNUN&zkRdAYCpl_^bOPaS2Zd6?fy<n_j}Tpi09{hU;8tmh'
    'z*Q1t>B(dq{Z>1hrl7t3Hm(}B91Q!!dY_ntn|>bxy_FyvFZG;+%{bA5VR&2Jb)lT~AkXw4Nz%uoOLa7ZD_e}v*8{1gqzh9O5`Ci4sNif*B7!sl'
    'cjXC!CZPzLSNM!iQv?ptB7zmJsgZjmtxrzRX*LXY-$dWrM1S=Bi{KOB`isR_q=~PUq4#NR_;6E<c0nE^Dj*~|wz7pIIZ*$R`pnIZW7~)?bBuXJ'
    '0V|Q1EiXA@auk6C35i=loRU^CC9nYYw@g<swg*j(7NRccujf@5p04-YFx|PHJC5REw+A^<PZz$mW-|>$AquljV8t3m5ndEv>yAgO9iTr}2U=TT'
    '>wtW~>{o~)TO&GbO$a+8r%farS}B1X4Mxa!p%xN$MEnT)2pWxP1eT?tN8+Eb_jGnUQ`b4*)NuqVILdtPW`<pN(YcZlRG(j%iovEg*(uC+0{`o$'
    'N8>w(SJe`Pcml{4wTO_RNfi;Mk@LXN%Pc)KT_q~(45ySyjW!huWMCq}tb_qDWCY5x>QpKP{Z_j#svTBT!-6+zYRh+uXb;`2ehY%M<ppt@i{rsS'
    '9umWD<1k`GKTdI;k_pQyE)el!4mqo0uwTH!5>y;(`j%7*(h^xKRA!q@nBn~}%h44%spxID_3lxUkUw@ZZ)V<0##saoW<1Ci0Sub>W;bUo6Sp?!'
    'aXHLnIvibF(8#c!vpV{U(+qa`<o$6>dec-Y@arh8p@IkR6~N!pKoQS;zaQoN4i?}lMT#3CX6kXU$>%5NEZZ!17A&Z(BS<-!s<HI<JGvqom(sN#'
    '{n0#wi{*4WHVCh-!+*V6D#P?rYgaoHbG3%#dL&;xV@|AhWWF-f*Tfn1Zq8JnR0UGt6au7#so@Zfo}iAv14O8Yr~;Zu5vY#?Y6htG)S-$pl~wd{'
    '&@m7F;`IFFU8|j$k9_^)%K^(nvULZSA1xdb%b{KD(%d*mr0~309#a>_JxL+ETvk^*N#LQuM#rFn+ep!E2}K<ziWs1W<-LIMC9RpPuQ@3~h>uXA'
    '%FB>}E-3J5-7p}WrzhwD@0#t*JV0HSqs!HFwXkcvHHYn{$eHkmmB4<r0spS~@sDirTiqj}KHsYWl2l|2RIy-kp-&=eY)VBU3XX(SQ~Q35fG*@;'
    'x@7(eR6T6kKJ*bPDiU8a#aNx53-lQ896(^}K*wqjnpH2=Tmi1g9T{$T0;umKu{MUX6{^R-9=s-|G9KY^-+H__HkX*F+2U%tyoqw&mT9NJS!#H-'
    'nVCn96WDK7BA`x^9YPRM@h^x_;fzGt7A<wUB?6o*B3)!*$Us(pf)26GbZ6iWUu@A$w`4+Q{kq{ofWpRao?p>@e<>`e&Roai0rEiPz#6urU&ELB'
    'tt~{%dm$>|9#dV36eoK=!-iQ?C=!M;M!`17=yRlnAI9i6=W!*p5wOiOj3~4b1p^}SNySEc4R~fzlDT`&-n}rzzvBV6xYXh3Z34lM^xSJL*-arH'
    'vzP44pW{>^B9%nQrJ=h}Wx!HIPc1E=<4WOE4FIRqv<9J5QSb*dW*Ga3aKf-nTtx@uv|Z$k^XP7s8}4}cg_><1(jo1wrL^!3y>iejBfw**=8wid'
    '7VgUrQD<kqzW3OGYzS>y3PeefRw_<vbOcioCt>gwf`%}!D@f!K<ODd(nF1{esQbnbax_Y+lgcM<TkKvw?YNe*XrO4MgR3hVhQmeyoaA40LErRt'
    'v%%jYs}`agNH>8rS#pCs2up<35aCHf=~|aHbR>|I#7LPVF2ekIMy`-GO?r~cd#4pYxPII(#oh4u#x#|&qGzqxaXEa)9nuQNbT^L^+lerb!E=w{'
    'IDD;LaotE=-voLpB*B3QijZEzx(M+P-V}kh^6@P{PZ&U?XQxzB)T9?cM{p;ASE@;n@!8UeXa~l(jG6y(bLhM6@$TyHek>~$ACz~0(EacOm{Bj`'
    '_ZqVn9rw=ANhVBhVpMMfMXa&xIbuGzoRUt%>^j?i-K~x7uEXvRd$3;a>#hkU>gn}6ZReYp&}(1FHsNIWc7Jbkg)6bRZDqJ31Z3n`)<FL?vv7DB'
    '4Xu8w9}H&>MAQG`c#YOG<a>*KFK^$w|8;Xw2D{c9#0u>w+io~dE4Sg80d8{%bemmwUdZ$H%%lDDMVD26>^*UQ+rHIe#ZGo%UiYafN}}Mz<C4v^'
    'r4e{*gAu)iqvI~S*w}*hhFaE6KS@&xpDY!_Drb&5%@PQhAU;P?+gB>CBQ%B;%w`oLOBsLh1suxYLZ&FeQ)X|r@dz9lkH&6Ge2^>}hi@G{cfWtk'
    '&Ag4|fKFe-tyig)&js~qKDwjKaP3yRRAFppMOIhuk0|4iJ#KRb$Bz>o!T`X)GiNYl;tBK8h{JPeBO1n`j2r+m!Zq`33`(b(Gn}T8UqsZ;5z#)G'
    '__yC|XOQCoryR_t>^g6~Z=XGV@u|f!+s+Y7uoe;k?Le0gJ0-nt@4hgUN**BC)v=5Nw2#x8tkpp`oPxc5BDld*fXXyYBR{HXh^mDBA0Szy;aZNQ'
    '1d_r|85h3aG<l#=lBtAG8P^Dd@@LrW_xZ(*^<DChfgN@lEv92->QU3lpyk89gSr0UqfdD%?Vi+<5M8*<>1R4G?9H{y`#>L9&R2&|0<=aT??QWE'
    'J&wEw&-_~EF^QGbSQLm&aAWN!D}Ck`|EKH2f;az5`6?fqzqVsEt<KD%gFExf$?}3b;M_1bR9Qy9jSp+1-z~?9u~y${(%nXz2A5Vz<L0t6LO2$P'
    '&v&_zNAvZ2U2co{HZFCaxPIF|+f0A%=G*f94v-Q@!Uo1>7;s>mW%?R#Wh|jkL~Hyb4dFa1Xb;C_Uf}5r(`CrU`Z^MDM3cs<KDje)o8eA;*yoO^'
    '>rL9hHaD^d-~JJyFT}oH_YvKo#JYuMNJHGj(C@!+)X&Fta_(^B4d1GX9{q^K2o!e7f6!Vk{J4VtAZA*-$s!P^L0&WdgZ>(zR8%++oUP#NWI%PR'
    ';@SszYTh>0nVgvart$4B)kMiWX=g_eNtNgmwswU08FRfhN&@B>ytsm~&D&7r`WezF`)seK*M@eKm-aOh;yA_+r~ts|TxStTB7Q=Yi2N*sInbV`'
    'Xw}e24$BZ410dK%kx}W4;#f2Vk`r=-o5s2i9(U;gL<75U2ZqYP9_?bkfuS_85Ir|Fs%Qlmj~Q4$snkqa7PmXQ!3Q4y5uU89DxcYcN+H!(^SAxV'
    'YK)~Kl7_!QH3Ay82$>#A<p8ST-l57DFn&kJI)O$ZqUTqI8q}bOql1__o#~++b~}d}haY{i-i7G4ZGbaI0^N8e6A==55$(xo!@WzaW}UAcpO{eo'
    'UsXp$wsYg5P6TDL*B^?kftU(tctj-|%m%E_DuWWV2?J0}bxP%fv4{XVP#B|&h{>QZLAj$!6Y{6VKTUtQWxD&h(+AHZuezy?%T2=}EZ@rU9n3|t'
    'lXcFT@5+KSjmB2A=6DD~>TuWuL;G!IxUVOO3z`Og14`U}EZhY`s1xT2x&m6nq=Ee*vgRjMR6v^U;|nkwWJ#ITx<C*rjZTEy;I^^OL1p0Tt-!jv'
    'WS{%equFvFZ`<Q=@OfZ>ea<87_jJYbPGNu;ZnlD`ZE+>MZB~$d@peLARQj0`@g0Yo=yG*Qeduy1zw8?`4FjZ{q()w6OkRuFMva0Kh;bj{sS=Kl'
    'Cc|x*L`75`KB_okv?xJ=oxUkAJC%UymaXnjj2oa?V;|_*E+x1U`$_a9Lq!4xkh<eqiIa3i^aGB=132L@mE{BiZot30nerZoKsX(uj?70pJ;WWD'
    'JuNd%5pDoUPSCS}p>T|lrfL9qkfBr`T>@3)%wOX?RdOoF#vaq14KL0vI~>T8^9aeBa05nTWNh{FleUet=Ge7VQytJiN@N$}-r^L~qhL4e>gZ|?'
    'l#wp+VUw(7!IVW+pixj2L5%1o^5|t0COH#(u!izu=sozKrVN5u2&=1@_$`j22LA%Ab1KKoe(T*IJP#hXEtWO0=X%E5T8=}<61hVRO8PtTn)&p)'
    'JB%>ex|@1TJ_G2@@^M3EVTyEpqBrQAqe5FSrj#<hN@)vHwk!w3P#Ud+un{LopkpHv1G<3PO<t!|rGYsx$q}8LyKFPuxv?K$gMqPu#~Vy7x6NXc'
    '%hP<zh4*^21nFbV<W*Oz$;-v@d4WUAQ><aVaMboVLZIMMiv!M!8bDjA;Uk3iLqRDGh$n&qClJEi5`lxbf|xLY%`+A8Ss-o9dq=@ZI>Hv)-Jcq_'
    'eZ_TFoRJoo-5ww_@eTeun9kavjdteGQil-IO^(lF9Q6f~!*fBd_c%;dCMl>G6rf_C1f?NiQ6cJ3)V|=2rdO{JQfnlK&l&N{k|y&74_d&;j@Hy&'
    'baFl*hq-OKGdw#i+P;IYblgzVFfp!Ty3-bwCiWVb`nfFKTAP8VqjCwO+2bCpy_G(|7&C!B!`~@YF5%y#XAk)xs>>qqfgW?wl)fLJKoB63)6f_x'
    'V&G#jfH49uro~UqA+{Rs+~@{rXc!B$WP<e4g%^j#zqUZ<DXv{&>H)HBkzOOwIIhg%aLQ-MK<EO7J_?!S7dp`Br`46NVGTiFwuB;~MqQKUA*~UZ'
    'YH5nd&@3d-L0QHeE~ir8+HJXe+UJ94pF1DvSf8D<fQ+08rHGq5+h{1-UdqL9U%dF*vp0QQj<lI%4i^fBxxU^zgq$b~WMvsNiOvOctZKB?0F40-'
    '%T&nF7+v-R)EKho!Z$(;7UvNu4V-O7*__(R(qp<aI9onvDijH{smxAxF0mFv+Z>?8nrgB};jP<-M_I7i5YO8^T}jy%0(6Q~fF(&O;*36NrRo$B'
    'W)Q+i*uve+`JxjaM-hT_zX7J7C?F|#MXgWL7v448nMGM!Ji(M~7wcj!U(cJX*Pg6F!&TK;>zKU2!lLb<g<6RUF~_9t%fL0I*gPmhjm%jIv?M6f'
    'Os9y{>L3bplUwK}qOqQVC60lhR6vG7XGN)`AnN3fg?{Uufj>NEMtHiAZ+&Zw-lW%^@ZW+=gub89gsiN#*&4ZMX>A45c2sU*h)pcYuD=>ZY1WT@'
    '(u@?Me_G`zG;4b1DM^T*Y6$%kMKlCi2;dT+^h_c%pO4Rg&*Bt0HD7qgWM_IH48Xp_OtENL`mI*ktSv^hjv-E9=TErrxAyGN^%1&&r3PYqGbBHK'
    't`MhrUIqwR6sd-IEtDZfg>H<h14R5(p5qp^NSPH3F+yt#iXE-L3YdGNqBuQGSGZ-mGjoad{x|Eg;u5Wga1=0GXwe|f0qA_wOPS&v0&P4pcc`^I'
    'Q{XIfo~g}p`b$w21e^lNtspCpP!@}TveVd3RZ#{iW8A7t>i`0a0>)0@h5!;1El6HY54sk9aC$D$Yrb<$9c=sBIKhSjY{yS)=Q&!7c}K%pyYWb+'
    '!rrlT_c=nIR%8J5<)9)&!X>ChMHz*QvX%xn0vEYoG%!2+4Km~cLW~OpEOV4Gl&}|`o+G?#wKH4)ucvdvMEi!helwut83g+)p{q4bIzv9>5)0E='
    '*B!O_QLTSxG!Ty0lKAbYAc1XCaS2VQk9tc%PcEto7zA+%QNXCP3S<*pML9w+h2mfUo$FI;jmnV7iS+u^`V!kMcMrS03+#6A?6Vh7|N6<`^C!=k'
    '%JrGby)8fa&=a(}*YP1)NNzh@*iL*Ll~YZpZ?4C~YbmP<S0c~9Z#oc{Q3Of|h1VJC0C|~3si4=(IKja<VRTxenG98uuOW0`Ts8+-sDdJ)YhIpQ'
    '`n}a~XLhv6&^{_k(u(^JPrvr8F=YN+fKg*vs>`YO)mMM}<rkj(SIAJ0YxTSN63a}mFU8PWBO*q<wPAXrhO!|J(lSj-7#_e$`Ot)Mx-bt|ff3<Q'
    '(e&z?yaJe>#hfeY$pLA5jdu=1<6W=KF!s~~N37s=b})6>F88oa38_LkI=z+%_Nd&!6o*@*u7x|cyF;T&mDX(WK*{UO&!EQgGr`j4jdUsC$pS%6'
    'J39>#->dUfxbe_7MuDsj!Z=Az%^iA;cUFhO;^w+vXqmBa04Z7iPRV=9hs<AfG$lvm1D(FfW#HoGJ~%nDNQ_jZWl<-U4<ayxDIq}MK7<GoTzOCs'
    'G9{r7$i<OSEz3NsV7e+}o%s=X!BboRTMc*O>~S|OVC4~RteaiHCqoKp$Z?D!j7buH6KrbAtVBwQ+e3(0w{v_7{cc_;^{eA5*ls1m+s35;Ca{X5'
    'JPpuUtuy!(v?x%LIK%~WuSpKY4rzN@<)S)9DHlGHBtVDHSK>F}$@$F|yPbpEtc9d3hrUp)NQG*T+x#}T_-)wb-YwFpqgCj}UpHFhN988coZsE('
    'E=9p!6-gG<c!F;H(ia*LvTj|~Op+%)$4#jCJuhIQ706SNRzfC6OCzpM&OvTk>|DDSVg-?(2L?+b(KWUyooRI~KgW55sY+Ju3K6R1@vVASif_4;'
    'hO?j#SDqK>6h~0dXW;x)1vzgVL%kDbG%-*W!zYxc`cw#yXq+X$1%nDuU{J#%(xmB0dcaoeoj2_1hI3q41DV;1xrmaPd}F#=3NX;XpN`BUtopQ6'
    '4f@<5h;<WWIu7V<XGVB6Df3cjrBV<dA<N%Kd4y6EK-rk{AuLr4oh~HSu<vFk=ms}TcCIJEXJ0>Ev~zS)V7;N)y-|`i<~pu5Z-ivmf}zw*;0Eqn'
    '{sBosmeQf~>rgrgWCv)g(x!_7Mp9vFNElA_^V-+3&pc|D(aZCzDA!Q6<*KYsZu$3G@60^G%-4-K=ObE$Vrv`E7{-GBeoX;Nw-O{~#UEF>$(D~@'
    'Z*rexJwOd%hl+~2rnLZ}w5GiP_8Vo&vJR2yfjNq%wh!0?Z>gb_3Lq&A>bP#uuS`yE{<PP4XD35!;9hc{GLE{I6}U}wV@=l5tQkm@1p^+VSFAaE'
    '`m}i{y`omHm?=#vVNqlG(}HI6m$hF6fSR%Zs0S<`75LXeL$96!_lpvm6%ewW8qi~#-R@x?hr>J`f3bn<aIUgGWL7f~a<g7#P3(!^$&@0$2TFzX'
    'o3ZC{`I5tO?W2DV=+Q+D^V#@Csmd%AGN>$JvKweEN^fPxtf>TAl%}Fo3n@+-$7!6XG|3BndS$0Ac01RUV@>eUT19G5(B3qxbCfvTyn9C+<sA)c'
    '=VosP#cB~g?I*BBc32gebn?QyDr;YHqUfLzqCuJu1?}!6X6A^fE2VM4uwA6X8eRLOBp{<`b#gB7uF=kIqJq8*Hn^TyI-4~;TCJB>A(W<^t{0Z;'
    '!>QC-VYcaPIT%fj&IR<|wl-~Qn$xH;p^iqL(J)4*2(3t|^9;~aS(M0gqtp$wBNR<r=Ia^=J#s|4rRN=-q7Ud(?rCpxg5Lz4B*x#2UXHppoA(!;'
    'HklA_eE#COovdpKIb^O><|sCL)W_9*>t@9ExdDusApq74WO#sVQ%srFXam+L-zsLXDZZ)<m6*VX^9kjctV$~8P4h~Zgi6iHp*yx3?jGH-6Wy`K'
    'bhOqR01{hm_Awq>hRrn&#B{-@<Kyxg5fdM}u40eeAEKEOBcT(`2zG{o48Nd01&aq~1&mN6<q;4-X7d_h^{C?z)_-78S%Yt>^3>errp3-IY_f=N'
    '(B5GD77n(g-&9%-h$}ssyXCBfmw<rj2;0>gk8jA4CJBDsHx~i>r6|A%sTo@73}0)sUqmfBp$zLo0f;O{4hdRPL@J}FQB=SHb0)Z9N-N^{gjfEi'
    '>CVgrEcvTD03<595Ty&aVV(FLH@%p#*cYaI*X7y99~jOX3oG?8ImBz;e)@U=U2tiKU3ytM6o{oLKsp)FtJc(JVHHmz*Z~o~OyZP|T>*qi_>>cH'
    'vSCTK0UWSS6Xt~I@12@EY&G1OIm6#r8?=+C3sMH*C0H%ARFPhe#$)np%X!ucR1TOWVx_{VTzYo6>KMI&LfG8aMurr?R6n4PoVsLKNB~QaIB9Tu'
    'kXZROBCk!=guXz;qX02I(v6bRs$W;o$W~bqK`^UN)+e@@?@T=-|2S$zj>QmKI@wE6MsoAmN~)}gge^^ez%NX1=cru5`1W2|@YshExy;ir&<Zvh'
    'A3AYAjKez08z4@BV#ZXFbqmROj!rTiiBjc_3aT_^iq1c|w0eu#j+uU+-Fa#9)V7~CZ0FeCgQK+0(HTb;sG_MiLGFkelU=$77`P$7iZ(dVK<yEL'
    'jhd0ms6Pacq0l};hruv^_Ki-EM$@@YN~TPiKuxtT&_58ep-!TpLDzyhRKpn(=ZIX?zUb<eO<0p>gPQY`Q}>>COn8=_w7ZD4ZJXXv#d>BF7z;II'
    '%@_g$H^z#O$nS)ed8{{3w*t&vtQMv#UW3(=uE{YvUI~rlOYCnRS|2Sl#N{*r3&y#91r!%DbH<eDdX$CMF@0~1q#q|#5@$MLJUkNZ*CZElfC7L?'
    'aiR|QuIcWNtS+`=$<9Wz8&LI6r9B7^oz&-d)AC~Bg!}A73oDr#i99+(Ot@ICa4?JJT^ys==*g?y1pp2n;R0!(stxlruOO$bk%6T@E=Lf9-zWi;'
    '=w-l>py6Q45tm`wBZ9fDtkSv+Pt;{@*zL@+94f(v*MB;HjlMAzVX}RT*p)Jv`Gx~yn~oKsg|&Cw=GKZw=@4&5vbl&DP#;K96@b&rfT}Ru%&}@{'
    '9+Co~l?0Ro`EX&Jf~*R443Uq?fHX4ZT2#JPWI&K7oT^9MFx>qSvU!A9+YH1u_BiRnt54nG;20EG(;%MJWHoE^9yQ?<F?tEqopCqObUQ+~X~wI?'
    ')ex$nzCuA2G*Osljo=GuAJRi)v?;3?2!~Q6$Q4v>VaZ@rU8hZzOL&F=EZ`K%$)JHx^%&VS+gWwrx9_$)QkTy>V=E~DsM%ixEL+CI4Rp8Et@CiM'
    'TnS+tr?Pc3di-ypMI?7QMxWU?9-@OJ!5N}RB^6>aA)F+1<jb@{AEQJ_gU&px3)IwLrm95kl{!L|B{8G4wH!z%>N7_@81joAGmBN(@>caJ3b>w)'
    '8>5xXzb(s=%d}_DaXQOn^=7!(sU)5=PYd^_MneE8vlNsg%+O&FMwKw8YY1~IbTptPiF5t|_E)4Y%Z$l%D1B(poUFs#G~In2?caVJeIYirtxN*D'
    '=T9HEzVpetzWvZ-MqD#9Hl}WdBZ|v?{@7b@Vn^s}lPP3?THdseD=sdX8_Al4v?h%Tjv>E<K2ZTSrVUDK2RRQ07&Y)1UYh%KK+!fsnK?+by!1pJ'
    '?S|dXtSIpHSI?jRZF{`fDzT?tO-Hpke_jp*d+#~xcvsWuOQY$eC=2j@M(c*cz-#sP82!PXmUeKcFTYW+u@j1s$iPz_K^W%?wFAda0N+&%uc$9P'
    '4rvbVUZeqI4k&njgz<!<rwUHgBi^yxxk)QiC#G-7nO3hVxm$~&Y`p|M8wVsdOV#H4W{tb>tXwtCk=Bjn6JL$=>!CaLOsmcfWNwShpz@)83G0b4'
    'I@B;LCXBboFhb}U*(U&IL9HZt0caLCg`bnmr~o0T1|TMp+KIZy4lABxHQ>-T=F|0*ZkN8aWiuhAW=?qEENMhF?U0KD4jgs$xvif|)Vu1dr6p0#'
    '*kYa46x47ZkoQR{ia1GBrA%xw>xJAVdYUR0HZ6ptzzg^UWlYvf2GpFaGreQG^ArXV><o9ZFjX+B#qFVEyH)KmBZH086$mwfY_^s>Mvqu6o4k)c'
    'h00e=jxUWyCfYNl;fE-gW@pSjhG`Mp3>4N>$I#kT=&Et7)OA$T-w(qoJ=sIWS?s<vwrc|3Im_>!fAy@ZB7ghh^Fb~LMt7!6YjPHKd1OP6B2=+Q'
    'eLQPqa79t>iX)~Qi&QcG7)1~cMP-f9ppTMTQlhE}*{CRiL^9|VR!uAig*r9IxM8q!<$RDCuDSls45>VR@%TbeDl`>0*K&I}$cb@m6Dxll%?^>Z'
    'K`*um6Z8r4gyspEcuAWiFG$W4rn8_9V#c>jA<znivO0@JSD8E=ymA_*WE`iq^tYJp%pBm!*WdoyN!eJjK<fnSjN4`Di_sqq6NFGsyNeA@-#(_J'
    '^M&bbhqMjY6HQtW1dQee0VF>VNz+h=MJ`WL8j5t^LzO~>Qm0TdB7>7?Q5UQcIDmLmMW^Tmox#pCEtsi=ozH4JfipcHIE5z>d$NEna9VcMv1ORE'
    '$-~jDeluir$Z^2(PYVVW{SeZVG!BppL|D0ri!>I|z$nU!47^FD;64dsm{DptdKqjlgD_39>=Yego9)gG!MI-gcC^_|wU=*OH|dr?Yz~eM>qt%k'
    '`Pwz?6)Of%r<c3vuh{baw5j1pWD2W76PEfAGrSO<C?uY0O;|+dB~_5EGq>yeL5Q$&5Y;e^LddI5rB1ZnVCP1C1^U()qLy0~V|W-tS`be5ZD8o7'
    'Ypa^<s1h%h*R!Kp^76%<D3=+n?8|*i)MDwlF@hUs(vqeIDigVoh9(*Tj)ZwCxDONb#8nvxw*&JaDgA7QdJ!d1r?lv|nCuLe{jXhsvtI6V&1^dB'
    '{k7#USxQJmafhmpu=UVv^9&K3eJP}-`jvpGV0a)!u8yMiW0Upa<y_6KhHL5PK6nNsxj70mXa>}QVsTUVM9MNxl}Nfm+)^O-3WG^rp(b9%s5EIp'
    'BdB~Ts-v{6PsIm%jdliJ@RcDf^vum~iiNY|yAh4cxpNe&<2M_tw*#q?9o>32J6K;2Ky;H}Fl0e%MSzp(5^StSv=SxPS}H(g4dq*!rU^1k2!@x+'
    '2R)0%A2aLl8=m4)Z|!vktNe*AV%k;i#3@ZVpO8id^tdJFTwiyUP0=xaE0!1;b%BM<!5$4CiJmbZRqKtj+XirblX>u;Gl-{%XhNc!S{0=q2sb(+'
    'OH8ab=x8X=MjCKyA<9clLygl<P@T!3Ld@e6Axqz3wR53LziooU=+U34InLod|LWUs9zF5gyKL|?%$N?>%TI-z!BJmb5j0&~^Q!Sh7e^h7+CXas'
    '5}NNUoA2;)#l%#vZl#9aP=|C3s=NR<jvf<SCIUes6GnZ5aw$B~RZxa_RZt*P6VX$qpaiRW5ZAZeN7%mPn+#g+;4PkHkKWra*x^#`+x9yZ&T%Df'
    '^3)sr+8aFg?r4<vwDemv#<Cud%J%^uviFA6q$QWyv)I3eoXC)ixaEFhqMH>y8?VR!9(vCo{}rtN?SePPVv)j-P6$Od{G{cDw)e%%g)rxu$M>n#'
    '=2)SBsYFWLy@lPnJc~-X<7(#Su!x~)kVjbdiWi5auu=)cPM4&<A#>QA0MtGcg<Q92w4&Rc!sJ=d5<rHvhPOvou@5j?Vy9CHgL;j22C>kKE2&qG'
    'q;O;IdMy_-nlv(Y?FqlLQ6XN)3a{qVg+&Q1H7cufBoXXf>hWym@+6lFDPNCz<yEtwsX)5X%|*LArI|%zH&TEZf&?sF6O$7FJ{9JV0{Z8)VGrl$'
    '^oOZ%(jSgbZs~6t>>N@67q-aaCN6==e<4(aUcH)|?S4Y%gW$`vHbE)LEc@%xrCrk|`~B<B9)0`mmq)ek*Js+c0*|j!*0>gu{-6<_8va>D!d=d6'
    'HRvBmq+-QbXh~&9tH95dMm{XkbOAC-fv2|SJ7XO)=<Ry+M*0xK04TY-MA3`)SNL&(-@?p5OYPGNSv+j}zYopA?+7_uek@M(#nUgJzBnphkW<a*'
    'iBrewBP>rqL+dPLS|Ii#%9&aRoB(-6wZBnuT@=huGicN_xgX*qVUfouUNEEsM@^7Kr{)pwnC#v!9(-*>qt-&6GmhtU>qYcsVHyN&PvA8Q8I!hF'
    'WL01~>8PXfj=2WfSoL**ae#`<HHU>J&nk2#Ndu}Hw&pYnQAA=62NpD3z)!_>ke;Lyh8lMc-+8W7l%1Sstj%@r6%T$(L1!@CJTh>NHhYq0L3dn`'
    'Hi!?jCx^)ttR``NRPNCB?fMQ1n9PwvszNCJ6)6L~GDytu3Wzs-&J4Jk63EUNuF=9pgUYIoN|9Ve=%QjC?bO_1!(8|7&?OVESj^M83!c>CEz`{N'
    '>14WEJoH+eMBVAwTZfR)$zlxE__!Rx8e7lRqJKa$4l<#?OzISpnIP8%Xo!Li8thC6awov%5be&QB!G{WT4`2>xnejo4Vo;$iB8Wg-Zk32bATth'
    'Mm9|D+;epPTnk`yZWzv~d4ib}$zthAcysl->nLau8=F+e(OI@nbf~D(@|@R|-R*us3SEMjXdq`U3-n+rjsvD@{1jn~9QAszLrgXUBq}uXHfbb6'
    '8F_&yG0iy*!Py7WCFnPbHvkznmuKt!FBAQGV4m)vW+BNA`S#y`>WLfiBt}ak&&yNl<bbZ#OX~kpAn$dJ?#Hr>*DvpkFk~G)bch85-IER2e4U37'
    'fh};8dhwUfP|4o-1oKuSbI%XDAHJ8S#>OuiW$ZC5Wz|kD--G)-UvkW-u_%JO-ov{jPt9n~x<c<*yV{lj`xb8r+OECXs$?-a6zk8{#CT<t)_CGt'
    'M64|_ZeKqRs=o|yMxAANPbdQlC@K+;g?Lgfnlmv)EhGlw9CnRFG1{YGJPSi=y+xu=rl!?nvNNdUexZS4&%N%h`I{JM;hFE{NgiUxoArE29Oi1h'
    'HuzeAZoF3BYDQJJK8|rsQAji4;IJO4%L#dwU<v!8FTZMXIAc+gsWhT`L0Q!$%fIH-q0GxD58~X+ura*ghl1dsybFSlK{m#AQhh3GzsF?vvDbqq'
    't!W6o77H0kcI`bow;)q%>z0R$&NhvB6b{jX5FJj<Ql<9_wo;kRa#9OFL0{5mAOYPyovXNMN||fOjVNVdMT?stm-aU9BN9syRLmbp;MHpr7gtF*'
    'vDgTte$^WmnXhPn{_h@|&yatZ*vP1oPFOdF+0Ol_F3pARUlL2%K<cBPGFJPkzSK#@aeCYg)?_p;1T&9+U?2ZxVE3@AM++JY$G;GO%19da%bzij'
    '+gPW9h#AV1Ea&fz5mc1WkO_=s;G%^48O&{7_<mE67!^pOWhiFy50$5y`8={J*gMLYL8OuvPFZCip8wvq%i%tJ!&A&(AGV<F>D>La{pUsow9sQS'
    '%Iy5*hJXDue*7N3*eUt)S4{)E>K06y$;Z~XnhgNHMU-u<lV8G#9qrgS7>>g}<xiN`(KVntj^rmKI$46|Aqkof!4w6NC`|%*rYim&6_9+Q{(+l='
    'L(pZ@5YHwj6O;BC?Vez#&D(;DFG8zyu7q7gT}sxrw5)4x#S#~<xc5&DBH!MKN!++(vXHaPP%})eI~`fH>YjTW<M-jvAXR`&1ijoOk(qMlPYS7?'
    'Cn@D~rmqwb1q~SwpiHti=FFK?<N^p70u<n);$;10!*1t5YUp^jhwD>PXr$h}1GwIKfe04Njl$GE06%wO+^e<mjgsJMVJ8~bUTDKc>v=S_7z&m{'
    '#kF$z<m0HEG%%tf`$q*#z!tmH#DIZ^I$@kkXXJ~O;65XSML>JPx2qyp-F@bNvyzcuv`6Z!Ap{jkceE7Hsme~Ja?)qAGpHJV_WZ@S&z`=3ZMRy='
    'I%JY@3hDaTt$1UJ3o-)E8B<e~W5`aqJEy=9$}H^Zv^k#Tzp;<DCu<+T2ST5;l!5mI_<xk;RT0KDMe@`SshKyp2eV(H?}tQf2)M;Lqrc$(83zU#'
    'bTVW=yUcb@ZeaHNF*nLx*d)Re1yy1|yXq+)T-Yyj(FI=@GvU9YPehaUh#Y|fX>=)Z1aGh3>=mPKYEb?uK!zaJDX9rzRm^mku))>3NYG=?(J~aI'
    'H2P9$BtyZmt}2z)I)nwW`b7pJT`G6i+x}U`6@Lj`j&7*Y%oW~wr13eLYBNz2(32IJ#NheYPd#T)YHqT>AiN=31Q#HmAw4mMxL8eA2FWw9xS!1^'
    '>SI~S!*9NQ=K4=I)Bn_KZ*sk*$St*JiV3MMx;}b`n5#W^8|x{{JNN^W9bKaVVlMfg^*8OqyX7=cVZSN>@TjIiqC+TilZ2lz8Q(z3-Y^mXLvAD#'
    '?7{$7fRC=z0)0<iW~VY9v)6WKa6||~&EC4Dd{D0kEi%Uq0!V<w|F5BK-j}wO^f#lIBM%NNRZ2<zC=Lf6s5!sfX)n6fln;7`#L|?En>eUu9wx1X'
    '`k^jUfg3b6!($;+^f@q|R6~DT2K*o^n4Ez}BB|n3Z>dJN3*fdN*vHrvp$B$~`XIl!^`^HxW4@Z0TeoleE4F2Mf|OoCanc;%FVan+b#kSvm$ND1'
    '??>!aTr_d1;@z*LA8$Gp=5tq*mlHO!UtQ5}lrpbPT}Sne>kg_s-@FsEEA0PDH&H%Y?(0Xt&$hdiH`{fiKY1m4a^qHh`W@gm_Ea=8&VS)O|NR#u'
    'I~982bV$Y<C!ZOLUI^w$u;HyuWpLCEkRR@;><B~3;3za~j-&U^GJ|>u>I&?2Tr#5oO_vNYD?|_j5*RQM5kHL5ie@i*)bLm^;hCT+l12Q7YTBt3'
    '(sr5cOs1LbS#oQnS*AOM&(0<MH>MZ(&2)Mc`0GpBwonc_1FBlhTs?2w@f26kbfKJHl}#R$khOsOfta`SlK_qilyS2n@?~U)LNaBpAO&=tA-t|t'
    'A*ug~Ecrf@oxyVd&1m^sI2ox~Ol%5bW|XvLtiGOd9@K`!QI@_K%mIH4i~ww$z5FPa{dihZhq-!N&PRfa5=y2%hz|i-9cpNKYo(Js537oTly1VJ'
    'h)Bzs(1{zJXNe|BDGLywRhS_Q1&jb*yEM=zLSWQmv7;j|`XxYbt}$+A_6LrsR4QEcU^*GU^{mZW;;*jYcRX%j>j^^+aWi*lNXhy-8ALK^U5F5e'
    'Qq1D8&ci&&a@9b{p3%o>vfPK=tJE4%O+{rZS7oRQ9|$P&Hz#uj>@?gNoCMFizTEF?@>}6#pAG)%U1-VL2hcSZxIY$f#Vfai9D@@~r<X*p_1x?t'
    'hXg{j?Ls;gz{FB%-9_~E3jRou3iLB*d}AMJgA$4t^7f)=qPWSK^rwA}xJ_02r!uU(+i+*#1drv;H=?26zIgGqOe5P!$fTxYd4;MBpOK|A(jo}R'
    '5R$x*9N{R&k{$UhI-ZzwUjrkBx0<2*5XCYE^RtB7Y@(3#W2AxUV+bBY=!}@c44`o@1GGG<Mm1q3tfp0h?AfWT{yv+XLmSWLw3g8HHPIDqgx^ie'
    '=K{_!pg{nX?*fEvD!{M|Et-KLXEc7YIHL8x?#k|@G%YHbYbjXPB4<gdHi-%T6}fK^0T`~s0%-z2NwTIa03aq!sUbX4BH)pSr7lk;Bj`2SxiFgE'
    'vcO^8zemzD{Gb2r|FrHiosTX}QM21aK56@cu8nsC2V%HQ9joclxz08i*=F*<M6ypCk6LJ%Wn=`*#^j;`s0-y6MIDx87iB}OC`9HagX%&F@r4Gu'
    '>qqdxoYu*4%Vg(JKr-_qCL?$xcm0X?{l9$w-+%bWAO7q2|N6r}{qVni|Igq5KkZ7V{QuDV;UD?Yzwqln@!x;`;eX|S|MC0(m!JJf@a9(+5^`PG'
    '7Qyj&gR>$BA&+lwJO#Cv2L7kAD$LP2la3xlV3DHh9o8_OQDZ7X%BO{*zS=;HS2u8|#wqA^>Z_GHDX-`^-5GetGq><<$4k~Xhr=JWNtUlawV0`O'
    '+wdkdwl<A#Ph9JG9KnwBcOV=(mg*IX=ki?oq|m^?HXIAmI8#-SQC7-z3iCDHgfPtF9CCOdA)uvT3C_W<(<{$um_r)|W3c)__^uDJ&c9`}(*D&E'
    'QM7MwuW0{ee<{n+{=)pt{_rRVGk?Kb`cOx~w&M8h(%a{e+pclK-8Nor=K=Q7nVTivHb31*jm84*xlM4sMt*jEd@3gllq<u^^K%WL9cH0Ti3=6w'
    's5EAD_n9QkIh_+KgK(Hf&=&e(P?S)(#eNmTS0(M!2>m*r2~#khwM^N3NPE_M-mE^%{pfznIbh5AG26%QS9&GG=Wfxpdq&$rdsh+Rq4#&6p&!21'
    'MQ|Y$Q(Zsv?$LX*Tec5~xT+#T<(_Jhj-gbED-95k)HsZ#m4GHx1iNF+)KD15be?@?R|Sia<s~fg$%nLk^x5U7+CTb+zTL04c;MRSZoBNyv3LBm'
    '-}v+yC~k!fb`w~$PDnMN9U=S~-QMsj)M_#`cQ^!@Jd(HT9RgvjHmsUj2Y!IWNsvV<r$55%dI_&<jn=I~DJ6vJxQ-CY@|g@Q%BaaH6+lFBDg%K#'
    'tacXZ{<XGKuG|hKU=Zx=kM&|Li6U4+?w$?CQ8j=keEiun?>i!|k~c!vYIPKKFR4m9eS@L2cmy6ya}>Mv6}=kRykS%EYi6ICFo2h#2qO5s!z`q;'
    '0%Qb1bQOZ61xn(>s1)Q#qbF&ha1J`}C*lA*?RHNnW{AH{&+wH&eJ|ZClYj|dv7TkYn+YuIMvmhZyYQv!c4YRLcwMiS%NY;a5|a)^$F!HJ0Z3I)'
    'Mt+zCkuQ1?S&3>;-NeW!`Z*kwG~E?LAdpXHb)ry+<CoyhAv&%zc*4_D@sRBnyZ4O;k2)yH0EG2iY+wK=)p(>uJZpn_uVLY%t<swDD0=P=Ny=1<'
    '3_9|ND?OSm`+Dv`OH>7~53~sx{lK)8<01oz5(NxP5i-#pX+miCputx)j0!MR##P{>99`vkk)KG<z29i}KwQ^8dD!yvY&1xOro@<pL!wfX=|slP'
    'J!id}bF{y_V{i!+)pT>T;ifSYU4k&(J4BmtQdE(KR)iKh|5w0IoQjf=kLYfLI%reXc|Zc;BNAHYsP8g02wNrCtsIu(Q)wg~WWO^=FTNCv)qri&'
    '^6OYjc%5|&OKY2GT(6cQz367prGmz?l7S{0T^)m4e1{zkeM~plC<21W=JA*2<<LB`K6?DPfm<hLVox`LN=tC)f#~OE0M-Ma(i)^YK?-{}tlkYi'
    '1U*Aoa;OM#Ytfucwtb)l&%iYvbrukLb%R<ou0ZjUrQaIG;Tv0GhL;+nYe=son;7Y1bqZT(HELm0#QNIo%xZ)XnnI$Gq0N}0vl{|s53>lAVicw^'
    '+7OI-pwydGKo@;RIg&<dRghRgWFMZcN8B>seWrn=N_%pC;yIIT%$K9iJE_L2dd=)z8G&|Ut#>?WA&1P7x(!44aIVNiGqts$a1rUcmqQV12FXFP'
    'IKv@ALM)(*jDHhY;Xg3B!CHkRdmSgResjja&p>yF<0fG+_GC054maW%oG9N|ea5%;9GPp8u}6W(KztTg5=gC&oYz$SwAb1S9+OLL!Z7qtCn7Cj'
    'G>VS)e7S~#Vn__R(tWu)pa#y12sxrWPGY4p!A1BbF43TBhrV?t;-?Vzz-g66=%p|_3n6b+RB>1-KRsdpxM92dljX+AGM-+Vw0!eqVTmK8LRXHQ'
    'eZaS&1l+<S#g?A4<#Bq7go?rm)`}MnS2IzC>CN6Vq#etoBrkzHAqgS0h6#=Wa3~!R7<+U4DiMDAG^`+`2M>vGwkmX%mT-ukuGjS2@!o?Td<Lwp'
    '5+0zj=n~bP7tM9K8jb69ioakeeX<;z;-kc798T7*Hpll2hux8S5|9XeKwwq`rKWiZ&W^gTpF|Pqyif8{7ciEjfyz~lEEmFf%&dnMgmb9kCE)RV'
    '1(G;c&FQ+(76YC|P_{l@lqWWTp+}^IO}R@7U>i{xbzyOntC8d`p6JbsjF(eD&`x@OV1&<(%1fs6`D(V@eAov#N=5oo=LjU^H4M}A-b+zTWl|B1'
    'lhjwG&m1>&y)@zDhJIp(bKovbK|=+mlaq6leKtHZUvV{Jd_ihsw}LX~DS%TJua)63<;PP4PBG)|kAHnk4$_r4Tc_W6%zX(AJU@)@rUe9}BqlJI'
    ';0Q8Z5|%Z@y{H5s@8ydkHyv1wC^1#C3i9eOMLi)n88P|;EqG?mu~;#auvoB+*X6C&Fbm;#kVc9!w{8jo!bNJ@k*bj+rLCWte;wa(BGg60k--%Z'
    'v>J9l7fJSUp->kVQWLG=!K#rBQGS^K+)_mq1Z4^5Ayn>)Y(E0oj0SfOCstTUn<XJ0OHQpAw$py+z}_qC^>26#)7Oi&4>W?m`ozQD9&JT{xRaNl'
    'qk%uNT8%m?n$6zq>g~duHBTQOlSiy$z(WEn4v5M&-BrnwR~ed9uz(hMP{5KUl`v{ze#9Uz+(5MDkwpdfub6U29yo|j%o}=bcV=fs=LnF5tpuW|'
    'x^qBu6X}(}+iuIgb=O5X){H~MN?h2?LYa<x%fJX<`%wr*5P!lAitc;_SW&cZLYU)pBcv&sAgiV?U(=v33i=}{XF|aFkd!Cq3%AX7U%$HHCYBXQ'
    '%`Z(<)g>CZ!KKy6F&@)(Agvv}W~?rcssxNM*8JT#d8imOkwKI`xGxf;CA^Bvx~D*Rlb8$y4mr*Q@b8(zivXzP#82=Hg>i_0VGu9^)}*N~t;O)v'
    'I`VsMc<(wlTxTOczi<I(=Rd4zl5;SSmscAHPiNtya-I1MiG-m^jt&U7;)u>W;4WcVRLn^=NQk5jdWN9mGX?)5MPDXN@<4^DNcM_!NF6A|4x>D-'
    '!{F4Mrr&yJ5ODp@Eo`LK#>zF~#R#4?0&RDus8p+ItLrXn_vH7WSU7QP%;ijSOpf7v+7OS;hpjwNpIi809)XpY5^f{F-!u{3TLy;7%NaH-0d`TU'
    'LXkd*1rW?URqp$enlP6L?D4~xC_daY?`c8boQ-`C1F*LkGP)ta>(QlMitT3a<S|QlMv+$h8Ry;KeG1ZF8A@H4k>&9iSozDofF}q*Nre<sGgNF;'
    'T&O4tWagC$5lo_aNud?~j0T;+Dx;!=%0M2%CSCh=Ui!K?vAuhz{m!meXS#G^g|3e+JNe3N%~k@|xB>2PEox^L5mK`D$NIQ-ZJYNGnLjC~Z_IP;'
    '!>E@LGBGuiu6TlsYm`CVl#MRnwyN2%0i#!pbd)uuaHypfK}c#1os7mw2yViYbBC>#J0~RJe6#7`pf8>^hi7>-T73<0wIWUK1kJ@UmRbl9lzA8H'
    'Kdmg<QMw0ZF+P+U@lem_LWQAg%c$Br8;dR)^L=HKFt-$?f{@ZEFlr>1G63t00Wt%tDi{`!)eKdZ1-KL1vn4rpq_b0XmR)u{2T=k&vHTHUXNW-s'
    'AHAF##vmKi3S(hU==#>qlE>v7lEw@rOj~zgVO+oJi~8Y3&`HFfh|1D_$Wpk1U?qz(o%nHq9s!*<0PDI)5t_wa(2|8&h;b;=1r=23$vMRi``uTM'
    'wx2WWq(Ci^Y`PMo4UExP$^uiDboolz=*u+l+Hz8xd3Z_)oF?KE3+hjcBXlVlPZ@Gzj)cQ#xK!7({>i}rpt^`V=@^Cu7#C2ejX_GK01X-M@I%JT'
    'GdXgK7#CxLFcz<pDRm{7-TX9ts>gum8k|`J2n_04N=mZMh1}YEeg!GROJT8erlP(yM)ClFlr2(K`ufOvdz%l~z=C`HB7}|_W)fY*I`T<U5rU$l'
    '2R8%wk0QcBR6%s6X<d|If<7A3<yjqObp!AgY;JwRe$krk%yM><v2Vg@#RFPy9+S6=iKGlG4R4N*(cFx1NM3T(9?)%ceRV9<Zc=y|b6VF??H5^<'
    '(ub&HUBa*s#yUu-xoS?02)cHLpGxQ(8G1q+2h4dMm#6LuoAx``6JpaD+JI?&ShNOOXDyvvjvdWd!U}n;KH|hI%<xDLbq@&gCah{gC|z<)Kvooi'
    'qJ`fO4#WV`H&o2wdDm5<X>&JeRnfAe<XfXE8<4}Fu!Gz*-dTHxoe(#sFhfbDS}V)S-Cxhl!foc$>kc7xq*LX$pYUix(XP)uN*JmdxWJ{yp;84&'
    'coF4IqYzoknh@571T+Y65IIrmLi%+uz?A_zM&<iSaq{lb8t+`)<7O_gn5fy}YPwvseQx6sTr_G%H&T!;={Q2yaBP0&A$QpMKK}^PAOWpGw~+c3'
    '1U@Amz|c5N5$N7>fpdg35_uUJMja-31nfg0#Hkq5pp|l({?TW_b9EAH4|t$CHKa+xf#JAyw=!QXC}O>m3Rcr*CK7xdrK@zMOQ1ar_#S|Y5;Brl'
    'GIFKDs7bRN-cVH5;9`hN_!wY@LqsR4;w;IE3Xa4aG!*UiG$e7Ml^C3;$Lu!b*#=+M8jh>pllhglOx2AyIS&zU>IfN*blUIThrKH?Ng~l(16K<Y'
    'N<~c&HBqRGFat@LRSj{OrURd4)VCn^DWGM5Td`IN!y91~<bHnQesYd!iGa)<vg(ud`d?=y>p{ORC$RyTgQW=1&ua4Ws1K4|$%wFvL}5V3gQ$y~'
    'JYmc=3AIAZs78sTPGL&WC9@h$Qbi!pn<NLEP9&zNc{S?PUE&;5k?k&FEYWdTb;(F|C0G-8mPkZp%Du#6ZQ08>QOkTKi}uJ}MJ9K59wKE<SA(_&'
    'nDbJaf6T!anU9QtDwt{#;CVw=9&yh^s$f|jz_rlO4k=0P%O*)r-eYc9@LZ!TYldwnintd)Sghu+_*x6+JA<wi>^$q3y+r!_L!Okgd0!%*_zk4G'
    'xgb&KoR<NmUpRTAFiR80#E}C5;afy?928oJ7m&MAFpuI>evvXq8=bhPY_Z~*wGg#&8+Uk!TqH!){Ahs$?go{p*vZ1UoX>O}l@G*Im~mwMq_3L@'
    '8*k_*KDb_nGSHL^D0R_2%;2XIvJtu^z#SvT1poi`&TYw!>^jr;eu@n0!jhtj$n!yMJAxwFYT7)BthTHxL>_ilK|}#107W((p$Nys+|4}0Jj2|~'
    'g~wq(L+g#^Tl<gzssI$}5!=Z`Ne-)6g+u1bz4l&*fBip9*5oEoT!DFH+=DuC1`hHVoTM}0(S~8#2TZJ`gDk`6W;m;ibzDG(8+8MJn%}$c-f@Mt'
    '#s0abOzK#5TttjFC3)S_8}Ty;c;P`*Rf9g7%0bAZo0IyCmorJ8K|qqD#fn-;(;S0yIQtzN{6ubhtkvSVRqX>t;K1eU`oyS|<Ej?UsvBp@S8#l2'
    'OYg(P(`PSg#qetrRWY#lIH*O}gOXMf!&t3a>Q*$`nX0NQjuTa*CkRUqw7l>pX64YG!`bd=J0$DWUGq&F11(MYs?=->0`_eeN^K<YCJE`GQ!wDN'
    'vTfo+1ua;0m=KY1*o1__r*suTr4XkGsFi-u1f&-n7;#Oo#e4_?yDcP$e%8cs+NSwXdm%fFcXT6$)+F4Yw#JP%yQyzovFbZVDTTI2cMNCq)A>~o'
    'ec}@c6Dq&1YM)kmQsoe{r&XksjDIsvh>8K2-H5-CWx$vVjeCN68X9Y~L!h$?lSmEI9gdtBS8ku1`@;_Y1cO4fVD)v+ub;z&`dKoZa$!djKEWS='
    'sngFxUA7967=?nCR06`C2(5L<snRH<Ll~AYv4;?e6krmgR9K|bAW&I`(+txe_S^92M?9R9h>4_kJ`qxe4U!Q{AX3ggc21&Ma(n108Y^=bx;;X6'
    '7UgBSd=2t~4a6dC8A26O!m|^XLEFZNr};IhH@t^A=R{cMs!15~NCSoovtc^OEz{j&6D4Re=qpWFxD8MII#7woyrJ#(1NBAHp2hwcs_|RDphqs;'
    'oplC1I%+mGjdEYqZ8#<ftq}6aNW9@V0YVZYvWXkX{{(qB&>r~?;~hO&gSCn4@lC`js8f0K88RG(4!YdrlV&ckZ)e5Qjnsc4GecZao=yF#kf16R'
    'Q4K;Rv^LUQ+T&SV)KIX&Jq68Y8^%FU1~NYtiv9-V(bdqD1rC|-$np%EWpozVsLeKWP03)A4D~~;u5|HM#-6kkt*J(7w1|{#|NiZ(m(Tm@B&+#+'
    'Y9IC8$wyk}<l0S=g!J&L7*2*bsxm0CXo(AX1FQ@U=)|^!L*1|GY9MZoMid-D3{%xvG+1BRYsI5YKQPGYl)!3gcuWLtcs<p8g#vWfzIAFd5SO8t'
    '7n)$KPtI~ZGZBM4m``vLfKpI+!g>qoRR#JmgZiz`h^%P$L1YrA$OkfU%PHbRD3|e@yum%7jcaQ;hX&>(2dsDOoa(oUJ%!WLk>J{NMC!NGUN!kX'
    '7_kJy4}P_nOE5SV{QbUD1LiAqnhK_&0?N2Kl!zH%^j4OBru-yr3+UA;>5Bd=y3TaJYnmFwTI4H!I<)lTkok_xBWU5l8MKg8!zpllfI>)k;+WZ('
    '0KWa_HCSrNH%n`8q$^q1S5&L|A*4B-UQ%DF-;K?k5i+mGw)UM7k&?<SHK)Qa8fj&eCCCp_57vKCq2<(y-XHvLkdc5C$^2T?;C2O&TO(fc=`MkG'
    ';-p@ES(h;1@t<&sJ1o~9Z?IPU|MQ0Rr&>!+Gy`xmx@m@X@`EtI$=ccRjn0u?Ehgs^aSVAY1}Pi#W+7G7M7bAwv;#`6x#75a{p#(R23=jK>6H||'
    'MCQ5f4V!vrfvd&jJ^Ri+KrUj-We}H5B$H23+hz=WkXLZFD0mc0idYqD1Z51Wih=YRoJf)~BPdJ_FfjT9IZ1X{>z*DCE=9N4H8SLfm39m<g__ag'
    's4Zc-<|Dn<gMr$38w}Jv@B`M(bbNk|<kZ+2q#2(xKfmuB@d1Ejp^Ta*l%}Xk#l%c#Y{W&(v=fcMydmRYQV^=@AW9gd4N}Br(<ld*8<bxMZ~7-$'
    '<>spHel05yACm8Q(Eai&AyohIfBpHt|M+h|{_h|E^~ZmAyy%;0_MiXTkN@%Gzy0}t{`h}?{15NX|MKJi;idA=fB*CU`0-!S58$Dm+G3P8qNk1c'
    '({ZiyrSr@A7|yJ#)n3ZN9K>H-<;-~l=RoPWOyHhsQfQ@BNPZ9&^y!ojc07)RT3sdlSd?`hHZ8<EYA6toTedoaWZ?Py@%+V{+abP^*w3?fZ@k~T'
    'mR|J787L0TB;B^G*>ZX+B<khL8e!R!eOsQLx|%EnqDEF%?L)m1zL4AI6-wSn71Lm7iiU9_#FNsx3Zq1zeB=T&;)?|7G5T*l+G0o;XV4yy6Ax>('
    '-?Z2ftobuANp{`ayZ7|nd%7m1qY+X4Ud)?o-FVsX4q6GkVcMUteLg$Cgc6i%yJL@s(gToE)<{U6Msd>kQNzBEmR>FLF8ntDs8lx~Uz<uW-?ZA8'
    'LIn*@T;HV8U{?JugB`)5e|2N;evTntsLQ9f_WW-=?oK0-r2E`${(W2R9k=wsz25g3T4)JV5WHiMnqof^M=?8oNC7Al(wnA1R+w-n0MA`!O#ws+'
    'BvR5AS;Ou>z*T?Sa7VEEpDaF}3XEdSNN#rgOL7=l%oC%P1hv15aXbn@GjxU5bOgFEy6l@Dybtf#_$$bj<GO{LgYnRq(tiOok3a`9G{ljDtce&O'
    'jga52q9`XKii5TYko;l-4pGUl9iR(r+3XlZF7`(7ntge#5oTf=?tJ5PIQ_@aI7=T^zC2ifQKjgWXffCQFw`__bD;qQfn7ymRfTm>msBC6qM@_p'
    'moY>EnXqIQX&5lxhAR;HGbmcOu#gu+X?pFk*nPS3!HczJnC83yfoIA8Oq2N3S!<)-(+?M*SSoL^$S@Eu^62(8x|&=DaRfcrlEfBufDVOX_L=S$'
    'bQ&$ROd*}%0;VR;0krc9Jf@;%kD_ql=YINi6etfE#XCJ+)(Z_Y{+pTlaH=~#r-uBIH~if<p12540w9s@cP{ON6;wd^j@qJ>=035?*}a_0U6dbA'
    'ED-I)@D7jlugs6`5BAzl03DEh{_V^8Z1cN*y3*;!A6jj|kK;<#@9g}GbPA@e_Al;Dx@4vXdRx5m8#_%j5ot0bQ^rw*OKIeI{jNM$KV2#Hvc4J%'
    'V1&=8Cew+YhCFxzHANN`N<u2%r-Ujj%mp<j>P}4zFCcRgz>la!p}SNUs9DDFqQxS&nlS|d-TzQdphI>$g6Qj!?e%I%-e1%In#%IkeRfaoXDM{#'
    'AMGzB*<d$%@%Xj(==C!;pg$0r1-&?Tc#NM0=teXfS>TegD)Vn}mgS9)sCFF2bQFA`t11Z);cjy{Gt;JllOrS3fTspJf(DXiHK28W^bl@Y$R9ZH'
    '1oB|@^vss7>WjHoV;MeP5)zir6*j;NuKST>%j2{B&${O+ztb1Fk2WBRL&S;M(i7B(3&N?28EMc&Rpkc?rm`aN(<0T9*|oHQV>|*DavvT{S`6iY'
    'R{cJ+^*QMvu2`|)gyh+Pe@H-9a*fL`>>*~~mjMO4_z80aLbOmic$rs!P$C0nF{$q+tbTDSf}P2{FMcA+VsTZQ?QS1bqRhxVGJK>?ArWsHzfMY8'
    '3{?bE8Q@f*OGcd-GE5qAOvEuG%F9Z4Hqc>34{S&da?4)#p0UF-F3YJ_>u&Ud7Y{jo^ZKzEL}}j3QUWJI4$-VD7fUPH+83X|ThZ4rD``3AI`5V!'
    '_T@iKN&8s|#?+6J1{q=m^5USWi-foPEgd-}Qs0S6fo)U8B7*>RN5!@skb@jH-o3Z%iL|!NrjL*%6Lf&PrLg73fUF%oUFOm=5SRRmavN>#-b7xQ'
    'QFH~yhVOX~^EjxxqCn6desKg{I6e?SsuRjqP3i;d0BwiLDjb*6;Lbp(Lga*MvBIGWWRv^>`O8gn9SMqKGrQ<yx+x!fqH51Q85oCH#wdn~8`x5>'
    'Rw(Yxa$mqcNd0fz$y@GeXDg9R&7iN0;aWm~0-^3SfJgwgnKmHJ0H2fuA!=Vq6%<ekC~&4UxtRu)iJy8vD}IN?zPg^qf7P)eZe#7|xmw(>HY(sU'
    '`9{6fNOo_y()5~n2T$`W_oNph3*njq!lg1g?HZ|kAjE=GLpUu-#L*!Zy}US4BAr*pDfka2r+vSIoCC2u8Ec?I72!Cf@`PX<G)*-m2ij-1qa!oZ'
    '{A4<(Hox2EG1IUQ*KKgeM{f=eb2;`Qnx_7~ZbSx{yJoJlsX|IrRAP}S(yKpGg8XA7x}i)}6Gy>RmM{^D&{xDDLmBu85N88g`n!#GWb0lx(_|}O'
    '${lK3c<+<~59PXKuG3~CrdfHZ`nm48CmKtdb#_mt5E1ngBo!=pM7I%t6r3wOWGFu(Vh33nGLdw_>AsOHz^hSYC>K?J3x<R-(RQe7f6H)3*qLZ1'
    'OUnq*We<(IQe+93vebw_O+jWScr;oHC}1y~KwV0YzL~V`7|z*J!pc3XpK4J6`Ac4rE#!@8%jW?7+6E0_7+n)UfQpP+kuk$Pme-M}MMMgSR1=DJ'
    '@L*Q|Zi^iQ`qe0%ny)#1OJCV085;QaLfhpDX2G^UOk_w+f3~Cs?L-d8zC`=x0a|{VeQI<7mnujn0sYB#4!LAP{DLM*3<G5wBGgzQ{7ab?A7JUj'
    'BqpP6@G4ay0@=Z^)_P~Ed$`|&M_013pK2mKZ5RGO;f+TBt%R(5SxN$oaL|dH0Xi}Ir9wa{j|$41{&>N>5>eHIGT3bK37Bufo0NDzm(ez=qcH=@'
    'Wt4~j3JbqZcrhwKC|`pKC+1ItQA|N=pQ&N_!VQDnd&Gn1EKcrw(=Y~#<Q(I)BI^}5uqB^cu0iy4)fcZ=oNJqv3ut!v0=eS75mDKws9@leRG65D'
    'u{d&p1nQ#zx(fJ-8QWJ#_#!k%I?R{^HKBkCYmv$<ziP5{AnY&ujn+HjmoMubH;G}iby&3J>>c%3;fyj$Scmyw9y!(*eP^Dr?&(Uaqi7S4Iuo0+'
    '>wLOAF)a)3VS4&UTtfbK&Li%HPsvrm7+3TB$M5+j3*Rj3>Antj7C~B!R|Sx|mUUL)Fd{jZ`3P&3Ed?e3u*%QDnKNcuLmrcdE#!O^{1`>0!l9fv'
    '2Mu?B@;rE<*Sj&0hQ(U3E#Uoj5@|`X$y=MQ<A@PS6|96!`r{#vJ5ai?@6ABTKI(xc$RPKw5cMtK9ZOOTd13;C!PBahhIJL=8U+b@!*n*xNfAL?'
    '85T_p4?&#{%0G6S?FiCwz54C4x3E6d$o#^E9y(zmPcE0jV$2Gb&`c*NtZ~kc4&Bk8)lWSP15!qxPUj!4r7_!$Z|oh)Rw0t{K5X}O9A<3^LcF2-'
    'K;t@1V%Rr|xPXbTss%z@!prBUZAn3jYHXwigmd}?^WC2nLR_GQu-`m=vN;;0OIMeh=Lj$lCVI7vX424L$qPfJS6w&feL*&DK5|E=b(gz@A;MZA'
    'v)X``M7@`;U5Nkqkk|nJP%wGW!Alw%9DapJUF$bBGIdb$;XpCi*`XvWciHa9a+bq`-n+cT6nY_geK%nYY0Gznys}q3d>ciHadka~ne&IM$zoqV'
    '4=<S_TB?E+dRA!6nBi7Ylf{0>FGxMoQ~@ea6dY#(AX-r7Fog3T3Sbq*uAv|S_Z#gPNDd~K@Y`d^`So(MrsWwU*dnhKuNL0h-##~>js<CkFyBlk'
    'SYz3@h41Qcve9YUz&)TQU>f{4Qz(@J;ef3v1Nd4uL|FI%DS2FnGFl2Jeq14ET1gVpmQ@bnao+mv09XGG%iV`k4_<9}g-N2lj_{e)t8^#a^hRpV'
    '0=tMM9d{(*J;MHNKJHeqi)#E~zIeBn{tU)SnYymRI7S6tdLbMRz?-5Z4xs%*!!b_UEKJH!Yu14ij0?a|XhcL10S?edwvBcKC&X{UUu`gRccGFM'
    'pIcol=GW&J5(-T_?9=FSa&A`kh*8FC<%zZUioQ93iHEOe<$Lr!<hkt2C2}OH(I=(+L@A0fhz3|-N}D6|6RFas5vAFdP%0EzI#|#IZcZz(fhdq^'
    '?da=Z1G&pGmhwaREtVS`A3wJ%bBnk`U!(bz{&9n`W2vSZvaLxwPCU~zC_mVL%2K@fPkD;^-@o`z@QM6%SNFA2jqGgWz(c+;6Hj(6SkV^?5<kT6'
    'Zz~VCcu90NwHadS54O-T!j6x^aSmE|`O}e;Y%Y1w`{iWe2m1)&vMj1O^=R??QQFpd6hi(60!%>e&@@zaO7Wl(zT1YO648h86C{&D7=)N>F9&!O'
    'Zdhz!=ipA4I1oA=aEG%GbMhoqTN@i4F1QbICC)s3Xx_jLkF-~eOs+Nh`+4<tB|66f!0E;DITPoW`5}rm`)Y4l!#tIW0Y{?WS{AJSG>?*6dkAAy'
    'j9kT{Y#hKIhs0h5)4z}87$dvL8Y6o#6wv%FTOC2P_;{`*SWjE&-ve_o3sl&0&p8Lqb;cwUwvI1a<6)2rvn2)*S_5I(i%9V*9G^#HW3YXP0u$v4'
    'MTCf20aH&&1oj2AJe38Na7q*@g2fP2WeNItC?e6>hasBTD5lUu2pWcho4jGEqZ~Bfd1PS9>r38749ChJp9dSu>A;!sI`n=M{mN65^NUsIDdwG{'
    'xec#0@!iQfGt<=5eK{q}f^hM{_{yq6?V7I&;WP<yYS0R?Vu18H1Xv~iq6iJJ7;qU8Ru1nEg=x5V!6Ab_hKM?Bsnpfgj@ewBH;E~FkW}4ai7&ML'
    'zqG!K1T`CW_T;usE%pBmCc?S*_Q^k-NSjfXD`Aba=*cZ+OBt4Z=)F}^PhNHTf>joD9EM$Vq^9$-`Mebvk0+WZi`w8pik)2IkQVK&7SgGNqA-Qv'
    'RM8_0U_XF=Eh<xJJ*z4bqW{ECB3RCA=nzyHw?O90uVD=yw8c-d3OD|+aW$X1I9H47Ph6W%^{(l*$=}3grzHL;WhUF>ie;~(SbVKxa29Aw!9Z5&'
    'sGHrZ=JPMTH19|^!#IKE3`s2Lo|+ah#fD023dK0R2N1X!fOAx<Yr55WlZREw7)I6BSyr}nsnR0*I@aVaBMfRW%0|f&H1~Ns0kq|fZaefw-XjDL'
    'E%RlE-ZRJgms*Z<iP1D$foA{JJNKBXuF&@H1LVQN3O7E%1#GQsiBQ7;QO%oxc{!m1Xd<Ms!a|5-z*j)#m%^YdtTSL)Q92w5w&D)U4O|9Po8aPO'
    'wGhfe%Zi{$#;(km*@5`><#s6hBshH%Z-)(z`*k7sR%}JFRToQa3tF;9Htb%6x~O9FCDJurBQiDjR(buy*zrT{3p}9mLle}mQIVjs7!>rI88{`z'
    'O_;6r+lI<vLvKN;ysFS)hm{;bqBO0EQHpRd>EkDw@K`{u4qmjji?_CmUi;VufHz0OshzaeHgX5Xq$l+gxqO-`<L+w5hwvCdBr2c*;dT{>pcX_k'
    'u)fkuLq|@26$VIuW_StJc42?bgb223MI2NW%%Kj+8FpLk*eGV40W=HQ$kkFjXCZ({%cU}OOBR=5WkP$j_ALa2F|qP|Ch@}FqInVkrC@RaxGGeY'
    'wXE|H6cT_V1ceY*uV620!B$ii<91n~N~GtYCu@qb$%CRTh7wdAw%ovis@(%|GS=|3+&fpZYl)AzE2inRAE4+k6Cc<Jmdq^N1r{1f+R9~>S8`s='
    '+g>>W=bDW1eH>eL>kSz4J_3#u)|o&U@i_|^uLgk{<y1n88h(v7W6~5ImITTf>gs+|NM0NT&^0wcTBD-OhISwvw%~oy-5E@VL?^Rr)2OwY>f;Wj'
    'eK<4u_SzDB)To*^+c`;BYL|5UWZOBw#h^g3bd)#p=zHaTHbL7bJpr=^hY4g(44&rbekrKS!j_*i&La>E&|<><1Pi$e>N=;r8^DrDZl9nK*+liw'
    'JZ){QW9Zmgkm~YcawS?421lc>rdLbY<T#x}-+6r0%*82MN(?Xv7y*z@L%|->0+}Es)6ViF2ogU>t5*mtQ-Le+>$XAUE^phx<r9bOcVwBx{K|q7'
    'Y~JkHa5wnOpg0q7+7i~cnZV5YGd<ls(A9h;6blHm?GrJj+Nv6sIoN}Up&d%H0j(_fDNAPG81w<VR>XDT!`X+(1pO}vkEtyAd0NM{YJ#D;z_!Ki'
    'Bc?THhvD-ZBL;Xmskao`4g^cTyI@tU({XKAIYl~}4&eiINsRQ@O!f9eUb&8@^x$^C9E*FGQsm@4Ph}s(jgv%l>R>;U35g2ni3}b<s<}014P1cC'
    'mO=@bqe=nxCug9jtaI|1oZOuxCK{Y;-LTmaoG7o|!r!P+c%%(L*#z*Z3$xlRqKAEAyL6?;L<FgPE1KF1>@{2UW9{n)2R5Kw%5Fo$a$4?Z#)Ka~'
    '5~wDG14@;3DRtN)VCgd_2PT44-EUF`gXjXnpq3J4g(dW9fP3IdP6xC0_t@-yX70gvxC1wPIcH8zsAu%#h&CAAyAKzN{eLEsj-GI(U0(?%NYlh#'
    '&2b0>wRy`@aL+v{<{Fuh3p$Xi3sz2}FLT@;;7*Qc+ex;}z+8k<UEqU$4)QF3I4~*^yMwa^s*W-#V0DTa77!`zxP)}DOodRh8ca3!u<7pE2R7IT'
    'oaoBBji*OuN`~%g#_VP?qHPSRn}FgzziohyK!juMy6ls?{83-qc(Q~w_@M47WU^t5FF-xpDD;NN*L_t+k<^-)tO*rvQM3u#UeI+gh?gJ{87IEz'
    'q%v+dnA2ph)sBINpmPF4=X7epO`T74_Rub2m%VsFbG^`!7O0zQ{zEU;zs9bNrD-WoRfH%HkpHRDuQUEzqju`6sLGYhndPXWMyb!yPy&FC;oF3j'
    '7REmY&@u)201RkZ1Pggy3}yN6HQF(hU^~_&8M%C~q10l5PG;!Vm^DCawK&;?Ls|Hr=sotr2{iOmTg0I&_w~JD5nz5MLy)V80wpO0|CeW3hT=*V'
    '1I0$B5%y&c0#Q^U)rN}zR8#>3F@%eJC=RgGU`L`zM?qRGq#*m+AciRxdFNWKl<e|Ci%z%$q14ngb~;#yl>4yS|5%O<Uz$d({Xu@*2l-QB5K@&5'
    '7#ma2C(}fWq6RLFBq$4nRe*Uw_=*&ERmXJRa)3}#lEc5>DkN9bP@<jP20NxeM+!nKnIATzk~;e}@xB}Qawu?8rHjjQ@y`40qh73a6QJs{Ee2fC'
    'SCRDS&VC%gB~TfRMKUU{WFk1w4LPtIX_Ciz3Dl!$fV~FvBS8KIk)jD#=1C}e))bM3vhqK{d`I91HiEaTt@h)*tBa3Iky1H*_CyCYj~+iiy(&M-'
    'K!bra;SH^f!}IvC&Fs8K4q>nJK&T&}4*^RI!99aKj5gAmE21P}hyrS*v@F}8_7#bM&oq2g!ytnWDZq?`E_D?qSvf2Z*tXYw&9v`84ENadsbu-$'
    '^q#eEwZl@}P@oB^bJh${#uRgawl>WFB<M~jaa*9i%dD@e+cNjV1Pw(MLd7aGZSm*K#`n4cddO@8pAf1iy4T)}cG$qSweR8*T1?I-nmxjeS9xVO'
    '!fB5X(=vGd{n^R7*K7vlI=E~v+{egNjJt4dpU6rE!5C^PaS7xOqT+^raYCgN07sS7G?iP3^<u?rC}1VzbsI*8lrNJKL70Mk9m*lG!(2y_46ix%'
    'oV1CizhaJgCF1McE6yqelxs1eO`vKY7W={v$1}c*Ltgw>dweL24h)0t!z!_)i(2JzQ2|p@d5{-z4lQd2l@@iLpg?Ab(oe{2DHA~m@m4hpU$A@9'
    'TF&~!vFBd#5H_$9cHJ|6eom+Z>PR9U`RDT6#r*Pxo<aY)8Abnv_hBN99kaLn`qA5`BeRW-Uq3qgZuIQsvork@Ph=&d!`+vhQ9O~4d~-b$Toc$;'
    '@8=A)kH_Lw<FR45>j279O#j8#PCxO+4;}r)k_V@@aoVzeOIHuoWBo>j+B4af<({M3`qS~uE&ND8RhB<&FP#t?>ePBFnUYR@KZI#JDci_rl_SZR'
    'B5;D<Pf|fTp4O^P@`TobqAym^L0|%?9tx;vhqVUIFK45nB@7fosV(1QSQpEpk?H!o;-tqL*7Dx?kzra8_}vGM(X(t9=D-l<R?|oj`Ffc)olXUY'
    'A#z)n{Wv}}*cOlg*#Z|fo=#d-f2{ZOvm(n5VLcEENaYv?RVdRzy~O|nVUiS_XrGlC^F(ohdKRA*3la%1EIb8F5DkUO`;gg=0^zM^K;7+I>iU_w'
    'riC{3WTa!d)jfc7;{%918pk9GG|?6d={WRg{R1bP?FV-=#*jdr<x?t#X}f@r7+Ll>D=Vn8l!9-LhC%{QF>=0Dk;JG|rx9KOfdG}&tW1Wr=-0No'
    'AKB^0@>PwQH4*kZ2p;$Le`Dz5A-1R?MQkI6&zd+<u!bhoiukWjag^E4fY`@JSDhvpcnEZ-g&8Bv5aX=}QYYGPw0n%)S|hYHv(drmXUXVi>F8(K'
    'Ew(v3%OI~^t>hRm5N!Ht&!4~OiFepx3k0%-$y<6qJlMT5Jq1Z{0^?y&<t3b8C?KXW5e@~RxKJ&aAaD_hpE4#Lg?XOxA~^@@q7VtJD9VSk(eJn0'
    'kqxjpTX@bEp0kCgVbe=Jqpaiml^{rGjn}mryJ@$6I>YkgrA$w34Q%g%&DH2rRaNLGNnA%|NcRkh9u(Or8xa+u)Gj>jG16~vN~@@rLq>^SBE_XT'
    '9<WpFu;0-;hxmjPfEG$nbxi3S8;yjPZ?V)<IwH|iPW$B&w}<g|!KZ-;k?5951Hm+SqPEIFPn3Q}6^WsK#Bf2)<;<ML417{Ois-xXf~YD)+$T;4'
    '=Lol~Ht^a}*JbNWpb1a!BD$~)7p`U2$q!gasT<*3Gx#n`D$bLCmW+AfX}?)eFRifXN)sOT!gZ$Hpt{Rt61vbdp6ghWh&qV@VTe{oov4BoMEJ$X'
    'EAmo>0>egoU3jKxJ22uIDbAANl#6az>nKhNeb*hd`d6N94~#6qx+VYc9N(Df7wEABqAI5+t!EB;r0eD$=9+Qd<z#nD<rXTeeBgI^UT0Ot5s{Es'
    '*K{5dC@5(|he1;m@KXv4b_i52ubR4mx)P~%<lq7|Fn_qqgvT|GV{LFt7Pq70qoa0p;Z)eQBCbg{&ZQ{TFGfoDgu4uAA5M>2Qw4H~0R&b!s8k;g'
    'KBkuyr0}YVNhVr~P<b8(BD*f~>q&_;Xxq}X2HG?*f7r0rQJxQ0_eqwmoxa@Wi@7W{8RhgEsKdjL<z-K@2*6SA2nB(RjN5C&Onnzby9`B~CTd}m'
    'Oj;RNhCYcAGpP516m~Em7iASOdd5o6$|j-Sgg7q6S_-u}NTgse3;zz=9f2FXWOH8#6x;hA<jIBtsF=nx*W)-Xw0^?!x|aDI)_0dnc;B6!z3!1S'
    'v;rj@>&LTC&nYROKVmc?gE@&bp{<xs<|H7>$>X{Tt0<>{1T{ArpPJ|be0Bk5BS#&iWnN)0y@(z5x^F|Q+YpYqUf;Et!T~r8Eo5C@$-kP;6HXnH'
    'Pd6ia5)0`{amQXVL(_dpDx~(3zQjm8KoVI4q~J)P&CKSXLtg>!YRsID5BVy!*b0a$iqT09(;iABH6^E7)FQqP4ctRk@lH>zOsw}eGxgzAS6xmU'
    'R+Ls_{X46VE6R`)p7uZUoXn%;8Et6Ne!hh5mUeBYRI95zMtJsQ`@Iu=mtU(K?aq8;MNUyp=euNOb%m-cUv*f&OVLv~(UYWPEB3kmgor<@h|yti'
    '#uwZI`^LU5IHjc`tTMlVN30QIRr=h1S~CBcP^g0W-Y;6Jx;1pG49K-{Q&flx#-T8P$ITAtpIcnFy~^BJ=T)a-GxcfCb?ZZKITts+ant6bf9@U+'
    'DjrZ&f0~T*t`E}QyY*Rr@l|fm82f!+BEJA~C#$l%x6#=@ZK@=jZx&W>?*#-(i;u5eIK?_PlF65IW<@`LExLO?JdYn&F(~bvnah%erVzMHU`FK^'
    'ji1Fq8br+WG)YzXh*(xWeA}c6ipk}ygrB}m{I6uAzuP8vEl&H^^~(IhJMLe8ExIOv-BZP&cKK~@s*l+^N3v$u1oN!LrEJQlli5$G*9|Evdw~F0'
    'SEN1+jqeNO6QqaBOoXUXKoMaDdZ;0hg^(^{*fMD1%BQLy=6=xDX$vm22;<BTnzjf+%9}%(qS<M$W2j%seS4H7XF?f4q`asnS_IJGo(-80_iJoo'
    'c!Uh&uaOgx;!Z_;)rUZRNfqL<9Lq2pUtLY62dGq<IAe|&END{z4}#RXPEfQAD`qdzUV{-kY~mP=1l6=r9fUw4>Z)j&FHmt%meF8V{Z5M=!McB9'
    '*R5wv;8-PCrBcFFW>~E0EGs2US^EYTfu%ppsOC5QNKo~)jwQc-ZwAQjZe*1q`Z=jzRxtBMr2<4s*`C2-M1&c)heNJxNl8`K<Yg#|2Tcq8JB)HP'
    'ec>Q#i@~h_gO)o2Klt_a^qu!%F<IG}myMChT8nVXUF+g~=NcM)yTC3>w`26h2bv8ju*LktzQqqgTtpyF$R1??q-k9F&`mc~YtWj9a)R)OB7RWA'
    'Ng9fVAhNOq_ia)J34GOs8q(t5VX|YW*{cs5qG{%?SpN&R?|<X0DkkYTS4y2kNsVe^ha-Em@~vdG?lJG{)-oJfltJY~zn;Si7qnHH3F&k#3~@=F'
    '70?XHd{`UlnK0(&Gw2rMsAlGXQL$mI`x^#3f>r-i-?4=ubQ%P%V7j54d7_Vkm6FP!Bmpzd17Th4*NS&2zJ0m_<f?657i|n*N`}^QAVkt^`BfML'
    '0EJert<h})z7SIxEK8O@m>ywZi6Lwc<6*7#4Pza_N`F2-*B#mAth`!YP>C@ijIC`O$p1>SDGKNrWg7wi|Mk+6Z1rf3FHJCNC4QOc*;k5$;kIC~'
    '7aUq4$eIeq#Hg(KA1!6Wh!~9OCG93MS<>5z5t#}O30kr+Mzs0BLYiGxJBC`0t&786A&brGAIlinbWRXoew2yc`O>a`(ZM{`s58$Bh<aA>N|vl8'
    '<miPfsB(dBiW|NkZzLXj=6%z)h9@1wS(HK#1W#6m40!Fg=mxYtnQaw8Fc%}}M1X^Ma-d)YDuWoLQjAveVB(xZc0003mv7JBdL4U%!QvQSkV>ah'
    '+t9ne*TOf0>&!VHsN7p5Q!m_LOO?(c>&AB4;E-?t)9+=%5m6D^fJuW6Jp_iCQ^A)p_{K*)89@!77Ajm1ahlO51=6fIHyDdAf_yLz@ktiEAB*qV'
    'Qg?z6cj;q<6mF<$q9((vZxACP6A2ifqP`I2HY#Ddv4X^;qKp&OCA<$RD)PL|C~XD=O~YK~yR3I)yT7r>sS9tUfo0|%dBv5UbNo&%fG^$F(CCpj'
    'xVh!-fyyl`=sNF}v_xCauaT;(Sn_RLQp2RAPhvoCw+4`w1p-W9{1=2;n^NG+8EMJGx(L%4zPMp|!y)S(fj2z5tR{NHH=fYVz&k6D`oan`mt1(h'
    'G~Hj+_jIw-`NRd(KYeruAp?Y&$l8u=Z=v?`?51Tx8eF0a18<x#C03xAp;duT5z2@J^`sn?%GOUIg}@zvGN)}A`B9$LK$!>X5xWg|Pc!`$L`mlU'
    '9f858^nJ57_9+WB%qJq30b_2?$w0d+tdm408=IWMP+Nr|>U(({(F?Ajg(If&YuqLsjtd+#-TmT!@X7-BH}IAl${X^n!iQLkZ4CI*``zT-WIYAh'
    'uX#qNPCnjHpgl~sg^N_^wu*9Coq-aHt0sg;7kaqTr?k|@BDsOCQWY`(0x>&ip`u^{7!*ZD*)<r9ryMfey`Svx6XPK=-+QVHt(&69Qj#SNX(yx`'
    '4O8(l4uDHcRezEVQ#vP4TIgW~Ej0JT-i~rX8?DXT1UiT)C{v)MKD?qJNRerRPX)%ITA{=zM0N17CvBWD?IKW8CV`XT<QV&m)@KJHuwSv*a1uL{'
    '#eJ;g8ox*^B?i$fDD`4;rHLY}we(<$(2<%;AIbcrfnux$pm^bIDPt-kcx*??`spp_3pw{hZ)cCH89g`@k26pgP;mvB593gp0n2DB^qjINO(M}d'
    'O9L4dLm4?wm>zDzSb{HTypq9s%%<Uvs8_dk0?Wc{?4X(x3q?9{DrW|iVW%-p^&xU@6kYr230(Y)ds*$L<%PR6W-dN!m=Y%W@L^zViYBEVMXw@a'
    'L^1-C6fi53pyCmLzeW!nx)mwa5`N`_b%ia<9pwpflez1z(BuGpS2u9u>R7L^?i+1gPmIjf{%S)=gwlu}aN@d*bhr)g^mHWAT%UYR1G&aBFvK!s'
    '(ECDIX7=?)m@m$Yrc}^g`-~Ygeg?H2Jdf122+m689q5=Sp@ffU6GHnXvp_JnP%S8uyd9Xc?K9mGoII~|^u>ZSIKcJoOJcITzI2qR3~qOak?Vu^'
    '2_U6ul*ZLmPk8Qu0K)(4BM#UW4ctRj$Y5qtp_JSpl^K$+$l-#*THH_uR<WN`2ZPJP7ryvX3S&cA^fyd(3{cl@%+j!JnR~a$4^Ar7(aZqD)WJSr'
    '{hf>G0psxIo#)ee#fsH`?ZtvOw!}$ix@@p-(Zj<MDsqUntz#82(}~;%g<e=GYLU`Z1w-(R^uSQ$mobPZ`0HTJ_7%)rc?eg_P!|0Ta~%V+!`*K;'
    ')j+RD$Tr9>WbN9yHaEr1l#g!sEtGhJ)UNb|rxc`mQn)pSl<QL;gl9)m#J&4{4xI`zHbA(^nwjUUQ1qa9n}URmX>I3OlnDJVun@X?CGhW*-gtux'
    'Kx5Q4(LhLv_S$UVDw_J{FFsZ@v^&-U?n_Z`x|8HL7=0U#zKwL~^D8s^yrGL`$RxxyEa@+J!jmpHaFj;9@Rt=_-q%;-cD2;-=Z)g?KBtL@^ij`j'
    'C_%NT2{svmX{d_FK?H4=6snL<P)x_s6=xcb^a#@UC?Z;_3v!CVj6xqY+%Z(7i~)>bxSa-F8$tIo>==dML>5X9jq>y2k_CKeT7VdF)r)eJn_Yq$'
    '>WX`|S>KiL+#doE($Ndi6ZGNr1^MdBU?@Y+@b@+W$Z`0sBkAzr2;fM-nET9DL~SJ`L%9muW+1L`xAE>Fvj5c!90r<pV&=Lq?mm^w+DG;^Cc#C_'
    'EKH!uYVx#dY1GAOQ?iWdKp-O(6-a;}i`g&~ktVswqxlsB|3hgu+_Ke?wXJW)Nf&A=em$~)FRKf;{3D|wkgu6PIuYXN6V(wM39!}Eln%HI*jdwi'
    'O6ZZ8EIp<3tq1Xp0AX1J%kG~$!3Z&(92hNaWi$dBFF6qifzlBEMu?Go)rK_?TEwP+6GpK@a}9}+v`rHqhl-N|XG@W19;9Dw8tonz^5FG#MIFgA'
    'q?f0{umdOKtXuldSSLoz+KG!uvawo7khM-WdgveO3WR*4w4BPm_Fe-cu#8rqubGMrIXbe?GXgJ!O(V~$6!B(+MQT3<rXHjrGkZbe<0C;MP{d{^'
    'YK3=L?w%|7!Ap~8yKLH8XrwK)#a_xs&N*n-zEFKMnYy)p5B!8G8Xq`z$KAdXEuuMo+<+a7#4nI5BmxV4nadLqHXrIS2DIax1RR1gpdje8wNNsp'
    ')URmA`2#sWZX4_V+<5RE>9+Uk@f!;Vv2>pz!X^-q>zNVNk)Q3@s=<W_4Rc?xARjK2nmTpXePt&<N`sQRQ=0n~Op+}BR8>_3qhyWRI1*EUXno=;'
    'P=cu{a}`GwjzI5@T2x)7LqUJsvei9eaHmkAks8s~(zynfbk5N+S<5i5Q(6!~Pu4Vc7m$dj6)Jv$0_|T}6F5RzN7Fl|xOT2q>*sJ&lFl-MuNCP|'
    'cD~G=e$-=_V!RT5^Sj?-GPAp0$J*6^8eYdpm|EQRdcF4Ve9;e+JHMD*QBBT;dry}h?|Qj*8_QUs7gtBMd+R;srIQVEY@<-K8MAJ^v~%nomBJe@'
    'bdTZoQNR5{+m3V7RhDt{M&P{rEt~-7YAo)5LyG3m%VkW@5_;}_gNs0M=0Dhb(Cv*queS95RxI)kTd&cK7GX2d``X<vmJ85VZISRh-(WuSN+(v`'
    '&O?A*zAq<w6Fl^`&wc%e`QjZ;Fkeg%D{{D@-Ea5<zApM73sqfDSV8*X>P06lsNL_;`;)zIyHz&hbJ&V@zx+~I{k3!euQT8`Sr>aQ$m%d{nD)+_'
    'z6!_Z(O6_&CksEo$cqCnj5`)^*2iKCig5d-?lX74X5ok98Cx$Nhn>wO+tO3K=N)&;aeN}B`>oB|1_qzEGrD)XBhj9xH#T}#bJK5?y}O>ym%EI-'
    '{Xz@fkr%7xj@N={yc8Xpty`PTS-Wnp0{^%&CoVMxW&UoHKlV{`uxZ{T8*ywN*blbO#`W#Vo(-Z>%nE3%i&bp%wA(L6E_l(=>PET4Gaj}ay?FCV'
    'mksSZWgB);i3wO7Pu)eiys-T#{d}CzhbK@qQ+C8Ec#M==EMdD9X%*g5`HrmzZolI<vHJr3)x;4}^}kS)g?!CgpyW64_}gdyboTw5rz3uR^Yrzj'
    'XK&nZyz=U5biLHjQf}NZx{DSERRE)#?C9LteMJOn{h*k^msL&Qr8eR0cbdgX)0lB-9mBk-4k;&-^G;nc6fv`e{jL)|!tab-*<`vI$8(OihpQi;'
    'tapS@9S4fRg~)WpQk0%aE2egY@1a@b^4@jwQ!cqj9XJ`C3BwEvZKjRL%wadOMH6nGFqjX$(2oa@)$-lsYV<?Pjx-{R((7}}m%8J(lU(iM^*e+R'
    '+=A9exivB?yPjS*dOf>^zZs#j3fB?pgV#^xaXx?Q?TBDc3`IYYqNVRQ8UP#X)Vh$ypb>MfmyIa|dQOUAv=*)zxfp)bv8~%hqSvPd@GQLvb#*Ku'
    ';pmnxKJ;GBHx`&(@%AH(PgtLlp#hzU$g=y>rvG<ws=FcQ--q%%X_f2A9D9oI(rxMXRMCNuH{8-W!BL4@tVqd;88W?^6FB_h8<}<(&sa+vLL;B?'
    'PGdO9R#tNCznkI5KbQFE#Nk;v4z}L6zV4g5-5OEo_O7*h(OSJ~WJY0Mm<t;@)GUgJOS@ND{D|JXtb-aV&e8WT|Ka7U-@QacaXLA7S&0h`Jhw)e'
    'j5^n9qWZC~guTi<Xfl+Koz{dA0Kx_mWo|qSo4RyCD>o*G?_XA`XX}xFvcS!4i~q(6ZktNFmew{#+-Z7eY+X<9MEDF~`D6pvf7&jTvd=-X#g#;Q'
    'BR$Zpt-KU|7%_F@EWBY-YwY%VrkDI3wtbMD%F(=5Q7|@uNZ8HsxFhH7caJ>KHC3v|B^7fnK1292R@pQ)`Wv*7DrUf-tXI&r)2(d*Yo-kCQ#OaV'
    't4xA6GN+BsV`cYqPH*;@cB<6sR+g%nP&CaqR|_|!{-s@WdXcTS-R+`)Fo!>X_4ps2KJny6rrzN&KwnQ63!H4VI~)&%4gd`L(0ow+(ZvSec>2^k'
    '6>19iUilWiCx7F8_w>z+r*Fq^pFaNn&9k%LkKdlXdG`41Z+*QnN{G>kugm(tM~vhZJc)YV?8eDq>)>DL4q1sN%Teq5oY-i_ZSH2hUua6AvA%On'
    '%F*?VMvq=U+k4kRcR$;jIHGxAjv#w<btjQMFw9{ivTQ58S>19O**QmNFJ3=+_C|}|2ve|xDAp-PH$y%VyOFRB4{fgNl`h6CH4SBjBb5M4q&}ce'
    'cPVFDRz3n7F)Ltf`+1T=I=bx}x3-Sz%noe}W{rBkn$M@i$41sf3Uq53qHiqg>yxMdc=qbm^S9$?FJFIu_I4xyClf2_c-jEMRC7DdeCR!Khr0D%'
    '9rAlNqVM)>tLL+*Cfp;Ybp~JaPu;v9W5|tI#H~PyStqm8l{|)<XSvtix80mHMvEX+8~oH#+`2_4B{u@xk4!$vvnCcZ_coi)PF)>Me~o2@abMRx'
    'Z1=t2bW5DK%vP>zDVJWaZD0bXZGRK5L<9BW#=5b=+S;>l0M%J&Bj?m-Ll=aLKi`hSK`wDzE3=TdgL0!nEcUV<^xdl$Pe<RsefsA0n^zL}-MF)d'
    '2HQ67v|8;wKJ+#sbP11nz%}RLxoWzrzNz;oxFU%jwQ|mF#Y1y;Z6!O}X-0Au@5p$***FO$Or#7Uf7Bmk@(JhcU10jq`?btg+oi%4ESDR6Xw6&_'
    'AD)<8u>GsaXS-W+Iq=3Ub)nJYM{nLdd-~>Y&5ZYE4RTMp&J#b?3KMJ*1UEW2GgmBPx<<Lt&fUGVteyIp^-OtYwC<}5;6!+wH)i>)2DJtyV!bYU'
    '*0463PxFPA>f*u9+ncArTC41<5Bwg8GvI$?v7_A4GwqHJ(`JeYE_EC^|2Fkq&%Rf0_}eF-c@p~4%v#baP;Ufp{azVyC~I#k7$S+=cINWUntEQD'
    'ePd#lU$<O4;81rn7oF2}_w(B2pWgb9?vqVE?e5NO$u9e~F_=y2I-k(@@nmjcuG$miNZj~r?UWC<iW4`wDH{Mn6Oc)c!FD?8yk3qQJ!fa$XuMlz'
    'Qxg-mZQ>4fqoi9C4?VEDvcM&Llk(TdZm{NM;@@_M-wZL_ZFWb2-FLUbEzj}2m}O<iv)zsE?0^aeOvY-vrpzU@(UU6~HL))|l^1$?3zIgBJO}UF'
    '@1H++vNH4c-AZ90nuuA4Q~G^kmYL+Yb|uON*HsT5dS^TqZHLn-`@?jzspA%teCSL*YQ3t~HFbAy2U=T#jVAP2H{{H&1Yw>L&e_;;x=-=kyR}WP'
    'N=_lOV@VInE{xgSPVwVv@9img%E>fsY&E9ajrEa;M+tW~+S$Tb*;!H!IOn_gfm!w4{jJxGyHS^mNMA(O%jQP@Yjb9Z>)K7uupw_Xr#it{2{G0r'
    '`gYsy6eLgU5&m`caYG4F?|mKhzTRHs>bI+{dZ9e@y5vuplHN>T#L~NYv>57;W;-CWUMN|WVK`@Bx}KSPk?-zYz?w_q0(bV>XAA^-_0ewKFMc<E'
    '{A?@-l8Z0i8X_N>k~0$)3uL-WH{=c|G04*3>A(K{*>|sAzJ7G}o!&%ctk&(%T@^+=Pz<ae$hv^MRh_<?%np=g9-edg*VRZ?Svy6wW@N&a(+{w6'
    'opvkq;m6DAPFj+rKnuV}4^NdzS|je5hiE*a{RL(VTDTx={k9ETpu#>IR}Lhlg6}Gia{wuI6&=O~+`c#+x$e1^NWoEEh+0AEBk|i73E&qc<BWPt'
    'tIV^I<XFa3Y9FLnQh>v(lb}kFn@6oFJbW$Vu`KQJcpo&UN+5@?A&E~zID=73$ovwz)FenMM1^yBi}E^5(8O$jOZy>;Iw{mfbpXt|NZR`FmzxNi'
    'Cq2@YEfZ?o&Dxhh$JYjB9Rht|K)*tj3TfHg&kA8}rLdW(5OVLFfgGv^Ra-`W1CvG_Gxd*-VR87PZbxgAU46c7Gi4PbT7{_JGF)ByHO2Bc;1c~-'
    '*wD&W=rfT!Pf-pE8mI=*nakp|Qcy)fc9VVn73qy}AJmX}*OJdo>XJ1O7a;^xd0f^lDy0qJLRdrMutM_=#f!RbiqKCK+&XE~WKvU!KmTetTyfG}'
    'z1bU#qnXb`gP1x)UNS3%Kn~rpre*y?vJ3SzETlo9;9xAXl1UTB&<h3mdX|;wGc})oVK$4}Cldm@3eN#qGiHQK)@)THNn8pi1gOilhM-HVBGiva'
    'ge35J#dVti+QdryGWp!=Ioze+y0kiqVV;kIRu%A4B$c408${WfJP<OZv}y{NlG+AES{4!5pcpY9{+zJ`3191HUYbqnWOw8w+()5YGcKL-eCoI?'
    '($=q=v`GMV`#JpL8B%e`jdLZHAid!efG{I3OW7UqLsZG@PeDw5TFYkF)m8EYBe3XoU166Zjfyx`A>0KOf{yH$4YdA&#uqAK{s>AK|0ycMBE?iw'
    'mESA|+U;nKRI!ym+IC!&U_GXj4cOGW&ih%rnmek;Zsb^Ra1rv@1=NXQ2{T+$Ghx`44O<MZ>lZ~5$e>kTZ_tmLfYDmama#WLL<BkSZQm5*-u$~{'
    'gxAZB0?Qa+&-l@k7thYlo<7-nY7ayvMWRC9zw_olXJzfYcgQHxR@my}n&l&VSj(_w#7`_P+z$AgUloD>#qRyPS8uuN@vE25e}BLZrrFYnFMpaH'
    '?sooN=GeN{zwnJxD1Gzv<=Obj)3=Y`JbQii>dpAkOL_KVDnDmWABz=SfJZ^;x8FZ|(^;Vl)$F$!siC!#h?cCtm&XSApykx1->x$xA_`YsU?6+f'
    'D*{(tv67nt8(&%Jc8IvUl-2ARzx?Ism%6B_&abhc3uEQOOqOR;S;=}VI^cG0XU4-_THvnVh{O81LJ`N00BAO0K@=8pauR4|a#XM>2SK$Sm#2#$'
    'd)B35-x!;O+2HqV1*2?*Ye}a{3-8yiirrOXbg{ujhNF!}z0R_A%zO?NxeOWUWI)>gH|wT^#@z#<9AIlQT~@G;>Sv;Ex?F#quG_gPuH!_I9A%@K'
    ';_BBMiL%YN-O6)0q(twclf7{<@G)2{j^y+@Z6{%YU8lTs$-T?smo|;JumN3`GTF^X{>)>ue;&EsQAM>tV2$1frOVFpJe7_a{`6OW`m6s3JVz-B'
)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def declarations(raw):
    """Immediate owners only: nested helper methods are not suite cases."""
    result = []
    for node in ast.parse(raw).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith('test_'):
            result.append('<module>.' + node.name)
        elif isinstance(node, ast.ClassDef):
            result.extend(node.name + '.' + method.name for method in node.body
                          if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef))
                          and method.name.startswith('test_'))
    return sorted(result)


class ColdCurrentCompositionTests(unittest.TestCase):
    # Explicit stdlib SOURCE suite: no SDK-preloaded pytest setup.
    __test__ = False
    context = None

    @classmethod
    def setUpClass(cls):
        if cls.context is None:
            raise RuntimeError('explicit_complete_packet_main_required')
        cls.peer, cls.original, cls.inputs, cls.module = cls.context
        cls.baseline_raw = zlib.decompress(base64.b85decode(BASELINE_B85))
        if len(cls.baseline_raw) != 278730 or digest(cls.baseline_raw) != BASELINE_SHA256:
            raise ValueError('embedded_d4_descriptor_drift')
        cls.baseline = json.loads(cls.baseline_raw)

    def setUp(self):
        self.plan = copy.deepcopy(self.original)
        self.raw = dict(self.inputs)

    def row(self, path):
        return next(row for row in self.plan['partition'] if row['path'] == path)

    def refresh(self):
        self.plan['file_count'] = len(self.plan['partition'])
        self.plan['input_inventory_sha256'] = self.module.partition_digest(self.plan['partition'])
        for lane in ('strict', 'legacy'):
            self.plan['cold_processes'][lane]['targets'] = [r['path'] for r in self.plan['partition'] if r['lane'] == lane]
        self.plan['source_explicit_targets'] = [r['path'] for r in self.plan['partition'] if r['lane'] == 'source-explicit']

    def reject(self, code):
        with self.assertRaisesRegex(ValueError, '^' + code + '$'):
            self.module.validate_partition(self.plan, self.raw)

    def assert_roles(self, plan):
        rows = {row['path']: row for row in plan['partition']}
        for path, expected in EXPECTED.items():
            if path == SELF:
                expected = {**expected, 'requires': [*expected['requires'], 'pinned_external_source_inputs'],
                            'entry': {**expected['entry'], 'invocation': 'Existing SOURCE runner -> main() with complete current inputs and retained prior COLD transports; full old41 plus current composition14'}}
            self.assertEqual({key: rows[path][key] for key in expected}, expected, path)
            actual = declarations(self.raw[path])
            declared = [group['owner'] + '.' + method for group in rows[path]['case_groups']
                        for method in group['methods']]
            self.assertEqual(len(declared), len(set(declared)), path)
            self.assertEqual(sorted(declared), actual, path)
            self.assertTrue(all(group['contract'] and group['requires'] for group in rows[path]['case_groups']), path)

    def d4_inputs(self):
        # Historical violations use the retained prior transports, never the
        # current hybrid/pin overlays disguised as an old source snapshot.
        if self.peer.ColdPartitionTests.retained_inputs is None:
            raise RuntimeError('historical_retained_transports_required')
        raw = dict(self.peer.ColdPartitionTests.retained_inputs)
        del raw[SELF]
        self.assertEqual(raw[OLD].count(MARKER), 1)
        raw[OLD] = raw[OLD].replace(MARKER, b'', 1)
        self.assertEqual(digest(raw[OLD]), OLD_SHA256)
        return raw

    def test_01_healthy_final_census_self_inclusion_and_raw_pins(self):
        rows = self.plan['partition']
        actual = sorted(p for p in self.raw if p.startswith('tests/') and p.endswith('.py'))
        self.assertEqual(len(actual), 359)
        self.assertEqual([row['path'] for row in rows], actual)
        self.assertIn(SELF, actual)
        result = self.module.validate_partition(self.plan, self.raw)
        self.assertEqual(result['file_count'], len(actual))
        self.assertEqual(sum(result['role_counts'].values()), len(actual))
        self.assertTrue(result['source_inputs_verified'])
        self.assertIs(result['native_sdk_execution_admitted'], False)
        for row in rows + self.plan['source_pins']:
            self.assertEqual(row['sha256'], digest(self.raw[row['path']]))
        self.assertEqual(self.plan['frozen_provider_sha256'], digest(self.raw['__init__.py']))
        self.assertEqual(self.plan['input_inventory_sha256'], self.module.partition_digest(rows))

    def test_02_classification_all32_new_and_this_roster_STATIC(self):
        self.assertEqual(len(EXPECTED), 33)
        self.assert_roles(self.plan)
        # Coarse file membership must not conceal separately admitted SQL/SPI.
        for path in ('tests/test_document_xlsx_identity_source.py',
                     'tests/test_document_xlsx_rematerialization_source.py'):
            row = self.row(path)
            self.assertEqual(len(row['entry_variants']), 2)
            self.assertIn('mixed_entry_contracts', row['requires'])
        self.assertTrue(any('genuine_suite' in v['entry'] for v in self.row('tests/test_document_xlsx_rematerialization_source.py')['entry_variants']))

    def test_03_prior_roles_edges_entries_and_gold_preserved_STATIC(self):
        current = {row['path']: row for row in self.plan['partition']}
        for old in self.baseline['partition']:
            actual = {k: v for k, v in current[old['path']].items() if k != 'sha256'}
            before = {k: v for k, v in old.items() if k != 'sha256'}
            if old['path'] == OLD:
                before['requires_sdk_absent'] = True
                before['reason'] += ' Actual final standalone body asserts agent.memory_provider and memory_wiki absent; class marker protects standard pytest discovery, not an executed native collector.'
            self.assertEqual(actual, before, old['path'])
        for key in ('native_targets', 'before_oracle', 'gold_security_assertions',
                    'source_entry', 'source_fixture_inputs', 'pending_peer_inputs',
                    'needs_final_rebind', 'prerequisites'):
            self.assertEqual(self.plan[key], self.baseline[key], key)

    def test_04_narrow_marker_inverse_and_old41_AST_STATIC(self):
        raw = self.peer.ColdPartitionTests.retained_inputs[OLD]
        self.assertEqual(raw.count(MARKER), 1)
        inverse = raw.replace(MARKER, b'', 1)
        self.assertEqual(digest(inverse), OLD_SHA256)
        current = ast.parse(raw)
        old = ast.parse(inverse)
        owner = next(n for n in current.body if isinstance(n, ast.ClassDef) and n.name == 'ColdPartitionTests')
        assignments = [n for n in owner.body if isinstance(n, ast.Assign)
                       and any(isinstance(t, ast.Name) and t.id == '__test__' for t in n.targets)]
        self.assertEqual(len(assignments), 1)
        self.assertIs(ast.literal_eval(assignments[0].value), False)
        owner.body.remove(assignments[0])
        self.assertEqual(ast.dump(current, include_attributes=False), ast.dump(old, include_attributes=False))
        methods = sorted(n.name for n in owner.body if isinstance(n, ast.FunctionDef) and n.name.startswith('test_'))
        self.assertEqual(methods, list(OLD_ROSTER))
        self.assertEqual(len(methods), 41)
        # The current transport overlay changes setup only, not these 41 bodies.
        now = next(n for n in ast.parse(self.raw[OLD]).body if isinstance(n, ast.ClassDef) and n.name == 'ColdPartitionTests')
        self.assertEqual([ast.dump(n, include_attributes=False) for n in now.body if isinstance(n, ast.FunctionDef) and n.name.startswith('test_')],
                         [ast.dump(n, include_attributes=False) for n in owner.body if isinstance(n, ast.FunctionDef) and n.name.startswith('test_')])
        self.assertIs(self.row(OLD)['requires_sdk_absent'], True)
        own = next(n for n in ast.parse(self.raw[SELF]).body if isinstance(n, ast.ClassDef) and n.name == 'ColdCurrentCompositionTests')
        self.assertTrue(any(isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == '__test__' for t in n.targets)
                            and ast.literal_eval(n.value) is False for n in own.body))

    def test_05_baseline_missing32_is_expected_old_violation(self):
        raw = self.d4_inputs()
        declared = {r['path'] for r in self.baseline['partition']}
        actual = {p for p in raw if p.startswith('tests/') and p.endswith('.py')}
        self.assertEqual((len(declared), len(actual)), (322, 354))
        self.assertEqual(actual - declared, set(EXPECTED) - {SELF})
        self.assertEqual(declared - actual, set())
        with self.assertRaisesRegex(ValueError, '^partition_source_input_membership$'):
            self.module.validate_partition(self.baseline, raw)

    def test_06_baseline_stale16_are_expected_old_violations(self):
        raw = self.d4_inputs()
        before_rows = self.baseline['partition'] + self.baseline['source_pins']
        stale = sorted(r['path'] for r in before_rows if digest(raw[r['path']]) != r['sha256'])
        self.assertEqual(stale, sorted(BASELINE_STALE))
        self.assertEqual(len(stale), 16)
        # Isolate each stale hash after healthy membership/all other hashes.
        for path in stale:
            with self.subTest(stale_input=path):
                plan = copy.deepcopy(self.baseline)
                selected = {r['path']: raw[r['path']] for r in plan['partition'] + plan['source_pins']}
                for row in plan['partition'] + plan['source_pins']:
                    if row['path'] != path:
                        row['sha256'] = digest(selected[row['path']])
                plan['frozen_provider_sha256'] = next(r['sha256'] for r in plan['source_pins'] if r['path'] == '__init__.py')
                plan['input_inventory_sha256'] = self.module.partition_digest(plan['partition'])
                with self.assertRaisesRegex(ValueError, '^partition_stale_source:' + path.replace('.', r'\.') + '$'):
                    self.module.validate_partition(plan, selected)

    def test_07_recounted_deleted_new_row_is_not_hidden(self):
        path = 'tests/test_tool_schema_source_parity.py'
        self.plan['partition'] = [r for r in self.plan['partition'] if r['path'] != path]
        for row in self.plan['partition']:
            row['peers'] = [p for p in row['peers'] if p != path]
        self.refresh()
        self.reject('partition_source_input_membership')

    def test_08_unpartitioned_physical_addition_refused(self):
        self.raw['tests/future_unpartitioned_composition.py'] = b'# new current file\n'
        self.reject('partition_source_input_membership')

    def test_09_self_deletion_and_byte_drift_refused(self):
        del self.raw[SELF]
        self.reject('partition_source_input_membership')
        self.raw = dict(self.inputs)
        self.raw[SELF] += b'\n# drift\n'
        self.reject('partition_stale_source:' + SELF.replace('.', r'\.'))

    def test_10_all_source_pin_drifts_refused(self):
        for pin in self.plan['source_pins']:
            path = pin['path']
            with self.subTest(source_pin=path):
                self.raw = dict(self.inputs)
                self.raw[path] += b'\n# drift\n'
                self.reject('partition_stale_source:' + path.replace('.', r'\.'))

    def test_11_source_absence_classes_cannot_enter_SDK_preload(self):
        for path in (OLD, SELF, 'tests/test_foundation_ci_prerequisites.py', 'tests/test_luna_oracle_compat_source.py'):
            with self.subTest(path=path):
                self.plan = copy.deepcopy(self.original)
                self.row(path)['lane'] = 'legacy'
                self.refresh()
                self.reject('partition_source_native_intersection')

    def test_12_wrong_blanket_roles_or_fake_absence_detected_STATIC(self):
        for path, field, value in (
            ('tests/test_review_queue_owner.py', 'role', 'source-only'),
            ('tests/test_extractor_shared_codex_auth.py', 'lane', 'source-explicit'),
            ('tests/test_source_suite_stdout_bound.py', 'requires_sdk_absent', True),
            ('tests/test_document_xlsx_rematerialization_source.py', 'requires', ['exact_source_inputs', 'source_stdlib']),
        ):
            with self.subTest(path=path, field=field):
                plan = copy.deepcopy(self.original)
                next(r for r in plan['partition'] if r['path'] == path)[field] = value
                with self.assertRaises(AssertionError):
                    self.assert_roles(plan)

    def test_13_native_flags_targets_and_source_closures_stay_closed(self):
        self.assertIs(self.plan['native_sdk_execution_admitted'], False)
        self.assertIs(self.plan['no_selection_filters'], True)
        self.assertEqual(self.plan['pending_peer_inputs'], [])
        self.assertIs(self.plan['needs_final_rebind'], False)
        for process in self.plan['cold_processes'].values():
            self.assertEqual(process['core'], {'selected_revision': None, 'origin': None, 'resolved_closure': None})
        trust = self.plan['cold_processes']['strict']['trust_core']
        self.assertIsNone(trust['public_delivery_origin'])
        self.assertIsNone(trust['sha256'])
        self.assertTrue(self.plan['cold_processes']['legacy']['trust_core']['genuine_absence_required'])
        for target in self.plan['native_targets'].values():
            self.assertIsNone(target['actual_origin'])
            self.assertIsNone(target['resolved_closure'])
        self.assertNotEqual(self.plan['native_targets']['ordinary_cli']['declared_revision'],
                            self.plan['native_targets']['hosted_full']['declared_revision'])
        self.assertIsNone(self.plan['native_targets']['managed_sdk']['declared_revision'])
        for key, value in (('native_sdk_execution_admitted', True), ('no_selection_filters', False)):
            self.plan = copy.deepcopy(self.original)
            self.plan[key] = value
            self.reject('partition_not_execution_authority')

    def test_14_current_source_native_and_explicit_packet_unions(self):
        selected = set()
        for lane in ('strict', 'legacy'):
            expected = [r['path'] for r in self.plan['partition'] if r['lane'] == lane]
            self.assertEqual(self.plan['cold_processes'][lane]['targets'], expected)
            self.assertTrue(selected.isdisjoint(expected))
            selected.update(expected)
        source = set(self.plan['source_explicit_targets'])
        self.assertTrue(source.isdisjoint(selected))
        self.assertIn(OLD, source)
        self.assertIn(SELF, source)
        packets = [r['path'] for r in self.plan['partition'] if r['lane'] == 'native-explicit-packet']
        self.assertEqual([p['path'] for p in self.plan['native_explicit_packets']], packets)
        self.assertTrue(source.isdisjoint(packets))
        self.module.validate_partition(self.plan, self.raw)


def main():
    if not (sys.flags.isolated and sys.flags.dont_write_bytecode and sys.flags.no_site):
        raise RuntimeError('requires_python_I_B_S')
    scratch = Path(globals().get('DEVTOOLS_SCRATCH') or os.environ['TMPDIR'])
    if not scratch.is_absolute() or not scratch.is_dir():
        raise RuntimeError('own_absolute_existing_scratch_required')
    path = ROOT / OLD
    reader = globals().get('devtools_read_bound')
    raw = reader(DEVTOOLS_INPUTS[path.name]) if reader else path.read_bytes()
    peer = types.ModuleType('_cold_composition_original_partition')
    peer.__file__ = str(path)
    for key in ('DEVTOOLS_INPUTS', 'DEVTOOLS_SCRATCH', 'devtools_read_bound', 'devtools_case_started'):
        if key in globals():
            peer.__dict__[key] = globals()[key]
    exec(compile(raw, str(path), 'exec', dont_inherit=True), peer.__dict__)
    # Reuse the byte-unchanged old main/reporter/lifecycle, not manual methods.
    capture = io.StringIO()
    old_stdout = sys.stdout
    try:
        sys.stdout = capture
        old_exit = peer.main()
    finally:
        sys.stdout = old_stdout
    old_raw = capture.getvalue().encode('utf-8')
    old_report = json.loads(old_raw)
    old_ids = ['cold_partition.' + name for name in OLD_ROSTER]
    if [r['id'] for r in old_report['cases']] != old_ids:
        raise RuntimeError('original_old41_report_roster')
    ColdCurrentCompositionTests.context = (peer, peer.ColdPartitionTests.original, peer.ColdPartitionTests.inputs, peer.ColdPartitionTests.module)
    names = unittest.defaultTestLoader.getTestCaseNames(ColdCurrentCompositionTests)
    rows, subtests, events, row_by_id = [], [], [], {}

    class Result(unittest.TextTestResult):
        def startTest(self, test):
            identity = 'cold_current.' + test._testMethodName
            if 'devtools_case_started' in globals():
                devtools_case_started(identity)
            row_by_id[identity] = {'id': identity, 'outcome': 'error'}
            rows.append(row_by_id[identity])
            events.append([identity, 'start'])
            super().startTest(test)

        def addSuccess(self, test):
            identity = 'cold_current.' + test._testMethodName
            row_by_id[identity]['outcome'] = 'passed'
            events.append([identity, 'success-after-cleanup'])
            super().addSuccess(test)

        def addFailure(self, test, error):
            row_by_id['cold_current.' + test._testMethodName]['outcome'] = 'failed'
            super().addFailure(test, error)

        def addError(self, test, error):
            identity = 'cold_current.' + getattr(test, '_testMethodName', 'setup')
            if identity not in row_by_id:
                row_by_id[identity] = {'id': identity, 'outcome': 'error'}
                rows.append(row_by_id[identity])
            row_by_id[identity]['outcome'] = 'error'
            super().addError(test, error)

        def addSubTest(self, test, subtest, error):
            identity = 'cold_current.' + test._testMethodName
            outcome = 'passed' if error is None else ('failed' if issubclass(error[0], test.failureException) else 'error')
            subtests.append({'main': identity, 'params': dict(subtest.params), 'outcome': outcome})
            if error is not None:
                row_by_id[identity]['outcome'] = outcome
            super().addSubTest(test, subtest, error)

        def stopTest(self, test):
            events.append(['cold_current.' + test._testMethodName, 'stop'])
            super().stopTest(test)

        def _exc_info_to_string(self, error, test):
            frames, tb = [], error[2]
            while tb is not None and len(frames) < 16:
                frames.append({'function': tb.tb_frame.f_code.co_name, 'line': tb.tb_lineno})
                tb = tb.tb_next
            return json.dumps({'type': error[0].__name__, 'frames': frames}, ensure_ascii=True)

    result = unittest.TextTestRunner(stream=sys.stderr, verbosity=2, resultclass=Result).run(
        unittest.TestSuite(ColdCurrentCompositionTests(name) for name in names))
    complete = [r['id'] for r in rows] == ['cold_current.' + name for name in names]
    static_old = {'test_explicit_unittest_setup_is_declared_not_counted_as_pytest',
                  'test_distinct_core_targets_match_actual_declared_entry_constants',
                  'test_native_and_trust_admission_remain_genuinely_unresolved'}
    static_new = {name for name in names if name.endswith('_STATIC')}
    baseline = [r['id'] for r in rows if r['id'].split('.')[-1].startswith(('test_05_', 'test_06_'))]
    statics = ['cold_partition.' + n for n in OLD_ROSTER if n in static_old] + ['cold_current.' + n for n in names if n in static_new]
    all_rows = old_report['cases'] + rows
    source = [r['id'] for r in all_rows if r['id'] not in baseline + statics]
    report = {'schema': 'memory-stack.cases/v1', 'scope': 'source', 'cases': all_rows,
              'total': len(all_rows), 'passed': sum(r['outcome'] == 'passed' for r in all_rows),
              'failed': sum(r['outcome'] == 'failed' for r in all_rows), 'errors': sum(r['outcome'] == 'error' for r in all_rows),
              'skipped': sum(r['outcome'] == 'skipped' for r in all_rows),
              'original_old41_exit': old_exit, 'original_old41_report': old_report,
              'original_old41_stdout_sha256': digest(old_raw), 'original_old41_stdout_B': len(old_raw),
              'new_unittest_tests_run': result.testsRun, 'new_subtests': subtests, 'new_events': events,
              'scopes': {'SOURCE_main_ids': source, 'STATIC_main_ids': statics, 'expected_baseline_violation_main_ids': baseline},
              'counting_unit': 'unique explicit unittest main; nested bootstrap fixture cases and new subtests separate',
              'classification_is_testbody_execution': False, 'classified_files_executed': False,
              'pytest_native_SDK_SQL_model_CI': 'NOT_RUN', 'actual_pytest_nonselection': 'NOT_RUN_CONDITIONAL_STANDARD_MARKER',
              'baseline_semantics': 'expected old322/354 missing32 and stale16; not healthy baseline or CI reproduction'}
    encoded = json.dumps(report, ensure_ascii=True, separators=(',', ':'), allow_nan=False)
    if len(encoded.encode('utf-8')) > 48000:
        raise RuntimeError('bounded_combined_report_capacity')
    print(encoded)
    ColdCurrentCompositionTests.context = None
    return 0 if old_exit == 0 and result.wasSuccessful() and complete and result.testsRun == len(names) else 1


if __name__ == '__main__':
    raise SystemExit(main())
