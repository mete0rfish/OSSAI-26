# AI Agent 워크플로 개선 계획

## 목표

- Development에서 풀이 → 분석 → 후보 생성 → 재평가 반복
- Candidate 승인 후 Validation, 별도 승인 후 Test 1회 실행
- Python이 채점·게이트·선택·상태·예산 관리
- schema v2 호환 유지, schema v3 확장

## 필수 계약

- Target에 expected 미전달
- 사용자 질문을 trim·요약·교정·보완·번역·재작성하지 않고 원문 그대로 Target에 전달
- Optimizer에 Development 품질 실패만 전달
- Validation은 선택에만, Test는 최종 평가에만 사용
- Validation/Test 관찰 후 candidate 생성 금지
- 점수·게이트·승자는 결정론적 Python 코드로 결정
- 같은 `family_id`는 하나의 split에만 배치
- 기존 output 덮어쓰기·제자리 재개 금지
- Validation 기술 오류·누락 시 `inconclusive`; 선택·Test 차단
- 서로 다른 split을 같은 batch에 포함하지 않음
- 정제 입력의 화면 텍스트 불변 검증과 hash lineage 유지

## 역할 경계

| 역할 | 허용 입력 | 책임 |
| --- | --- | --- |
| Orchestrator | 상태, 승인, 해시, 제한, 요약 | 단계 전환·중단 |
| Solver | prompt, 질문, 현재 HTML | 답·근거 생성 |
| Failure Analyst | Development 품질 결과 | 실패 분류 |
| Prompt Optimizer | baseline, Development 품질 실패 | candidate 생성 |
| Workflow Repair | 구조화된 기술 telemetry | 개선안 제시 |
| Python Evaluator | 비공개 expected, 모델 출력 | 채점·게이트·선택 |

- Python이 역할별 strict payload만 생성
- Solver·Optimizer·Repair는 파일 도구 없는 provider 호출 또는 별도 sandbox에서 실행
- 해당 Agent에 dataset·output 경로, 임의 파일 접근, 결정 권한 미제공
- Repair에는 오류 코드·retry 여부·attempt·token·latency만 전달

## 상태·산출물

- `phase`: prepared, developing, awaiting_validation_approval, validating,
  selected, awaiting_test_approval, testing, reporting
- `execution_status`: complete, partial, not_run
- `quality_status`: pass, fail, inconclusive
- `approval_status`: pending, approved, rejected

```text
<workflow-id>/
├── development/<stage-run-id>/
├── approvals/validation.json
├── validation/<stage-run-id>/
├── approvals/test.json
├── test/<stage-run-id>/
└── test-exposure.jsonl
```

- stage run은 실행 중 원자 갱신, 종료 후 불변
- continuation은 새 stage run에서 `parent_run_id`와 부모 manifest hash 검증
- 승인 기록: 승인자, 시각, 범위, nonce, 대상 digest
- Validation 승인: candidate, Development gate/result, case, model, config,
  scorer, 전처리·retry 정책 hash
- Test 승인: selection, Validation artifact, prompt/model, Test case, config,
  scorer, 전처리·retry 정책 hash
- clean Git 강제 또는 source-tree hash 기록
- 호출 직전 승인 digest 재검증; 불일치·만료·재사용 거부
- live 실행은 사람 검토와 외부 전송 승인을 라이브러리 경계에서도 검증

## 실행 단계

1. 데이터 계약·HTML hash·family 격리·사람 검토 검증
2. Development baseline 실행; 기술 실패와 품질 실패 분리
3. 품질 실패만 분석해 candidate 생성
4. 동일 조건으로 Development baseline/candidate 비교
5. 통과 후보 하나를 봉인하고 Validation 승인
6. 동일 case·HTML·전처리·model 설정·retry 정책으로 Validation 비교
7. Python selector가 candidate 선택 또는 baseline rollback
8. 선택 결과를 봉인하고 Test 승인
9. Test campaign 1회 실행 및 최종 보고
10. 별도 승인된 HTML variant로 robustness 평가

## 게이트·재시도

- 후보 기록: `candidate_id`, `parent_prompt_sha256`, `iteration`, `change_class`
- 설정된 최대 후보·반복·요청·token·비용·시간 적용
- 동일 candidate, 오류·answerable 보류 증가, strict pass 감소 시 rollback
- 평균 점수가 최소 개선 폭에 못 미치면 rollback
- baseline/candidate의 case·HTML·전처리·model 설정·retry 정책 불일치 시
  `inconclusive`
- Validation 전에 후보 하나와 실행 순서 고정
- 기술 오류 → Workflow Repair; 품질 실패 → Analyst/Optimizer
- 재시도 허용: timeout, rate limit, 일시적 서버 오류, 빈 응답
- 재시도 금지: input, approval, lineage, prompt template 오류
- JSON/schema 오류 정책은 provider별 사전 고정
- 양쪽에 같은 정책 적용; 모든 attempt·비용 기록
- context 초과 시 임의 절단 금지; 전처리 입력·코드·설정·결과 hash 기록
- 같은 HTML의 질문은 exact sample ID 계약으로 batch하고 사용량을 중복 집계하지 않음

## Test 단발성

- “1회”는 승인된 `test_campaign_id` 하나로 정의
- provider 호출 전에 case별 exposure를 원자 기록
- timeout·빈 응답도 attempt로 계산; retry 상한을 승인에 포함
- continuation에서 성공 case 재호출 금지
- 부분 Test 재실행은 대상·사유 별도 승인; 결과 혼합 금지
- 모든 Test artifact·summary·error·continuation payload에서 expected 제외
- 로그 제외: API 키, 전체 HTML, 렌더링된 전체 prompt
- dataset·HTML·prompt·config·전처리·scorer bundle·Git·artifact hash 기록

## Codex·Claude Code Skill

- Skill 이름: `run-dart-qa-agent-workflow`
- 목적: manifest를 읽고 허용된 다음 단계만 실행·보고
- 보안·채점 로직은 Skill이 아닌 공통 Python controller에서 강제
- 두 Skill은 같은 CLI·schema·문서를 사용하고 도구별 진입 지시만 분리

```text
.agents/skills/run-dart-qa-agent-workflow/SKILL.md  # Codex
.claude/skills/run-dart-qa-agent-workflow/SKILL.md # Claude Code
src/dart_parser_workflow/agent_workflow.py          # 공통 controller
scripts/run_agent_workflow.py                       # 얇은 CLI
docs/ai-agent-workflow-plan.md                      # 설계 원본
docs/workflow.md                                    # 실행 계약 원본
```

- 시작 시 `README.md`, `docs/workflow.md`, 현재 manifest 확인
- `prepare`, `develop`, `validate`, `test`, `robustness` 단계만 요청
- 승인 대기에서는 대상 digest와 요약만 제시하고 즉시 중단
- 사람 승인·외부 전송 승인을 추정하거나 대신 생성하지 않음
- held-out case·expected·원시 결과를 직접 읽거나 Agent에 노출하지 않음
- partial 재개는 기존 디렉터리가 아닌 continuation stage run 생성
- 실제 실행 명령과 결과는 두 Skill에서 동일해야 함
- 공통 로직·명령·정책을 Skill 파일에 복제하지 않음
- Codex Skill은 frontmatter와 선택적 `agents/openai.yaml` 검증
- Claude Code Skill은 기존 `.claude/skills/*/SKILL.md` 형식 준수
- recorded fixture로 단계 전환·승인 차단·누출 방지 동등성 검증
- 각 Skill은 격리된 임시 workspace에서 독립 forward test

## 구현 순서

1. 공통 Test redaction과 Validation `inconclusive` 차단
2. 상태·승인·stage-run manifest schema
3. 역할별 strict payload와 실제 접근 경계
4. Development·Validation·Test 독립 실행 경계
5. 단계별 승인 artifact와 라이브러리 검증
6. 기술/품질 routing과 유한 Development 반복
7. typed 오류·retry controller·attempt ledger
8. continuation lineage와 Test exposure ledger
9. 공통 controller·CLI 완성 후 Codex·Claude Code Skill 작성
10. robustness·schema v2 회귀와 두 Skill 동등성 검증
11. 단계별 테스트와 `README.md`·`docs/workflow.md` 동시 갱신
