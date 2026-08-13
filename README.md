# OSSAI-26

공시에서 원하는 데이터를 잘 가져오는지 평가하는 파이프라인 구축

1. dart-html-fetch의 driver를 이용하여 DART 공시 HTML 원문 수집
2. 해당 원문 HTML에서 질문, 정답을 yaml 형식에 담아 LLM에 전달
3. 모델별 검증 결과를 바탕으로 프롬프트 수정

* 사용 모델
  * gemini/gemini-3.5-flash-lite
  * nvidia_nim/google/gemma-4-31b-it

