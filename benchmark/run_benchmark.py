"""Evaluate real model outputs against frozen, aggregate-only reference answers."""
import argparse
import json
import random
import sys
import time
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from getpass import getpass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from ask_database import execute_sql, generate_sql, is_refusal, validate_sql


def compare_rows(actual, expected):
    if len(actual) != len(expected):
        return False
    for actual_row, expected_row in zip(actual, expected):
        if len(actual_row) != len(expected_row):
            return False
        for a, e in zip(actual_row, expected_row):
            if a is None or e is None:
                if a is not e:
                    return False
            elif isinstance(a, (int, float, Decimal)) and not isinstance(a, bool):
                try:
                    if Decimal(str(a)) != Decimal(str(e)):
                        return False
                except InvalidOperation:
                    return False
            elif str(a) != str(e):
                return False
    return True


def select_cases(cases, limit, seed):
    if limit == 0 or limit >= len(cases):
        return cases[:]
    rng = random.Random(seed)
    groups = defaultdict(list)
    for case in cases:
        groups[case['family']].append(case)
    for group in groups.values():
        rng.shuffle(group)
    family_names = list(groups)
    rng.shuffle(family_names)
    selected = []
    while len(selected) < limit:
        for family in family_names:
            if groups[family] and len(selected) < limit:
                selected.append(groups[family].pop())
    return selected


def main():
    parser = argparse.ArgumentParser(description='Olist benchmark; default 20 stratified cases.')
    parser.add_argument('--limit', type=int, default=20, help='case count; 0 means all 280')
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--auto-execute', action='store_true', help='execute validated queries without per-query confirmation; local demo only')
    args = parser.parse_args()
    if args.limit < 0:
        parser.error('--limit cannot be negative')
    cases = [json.loads(line) for line in (ROOT / 'benchmark' / 'cases.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    selected = select_cases(cases, args.limit, args.seed)
    print(f'将测试 {len(selected)} 题，最多调用模型 {len(selected)} 次。请先确认免费额度与费用。')
    if args.auto_execute:
        print('自动模式：不逐题人工确认 SQL；仅适用于本机公开练习数据。')
    else:
        print('人工模式：每条通过检查的 SQL 都需输入 y 才会执行。')
    if input('输入 y 开始，其他输入退出：').strip().lower() != 'y':
        return
    api_key = getpass('请输入百炼 API Key：').strip()
    password = getpass('请输入 olist_reader 数据库密码：')
    if not api_key or not password:
        print('密钥或密码为空，已停止。')
        return
    guide = (ROOT / 'database_guide.txt').read_text(encoding='utf-8-sig')
    output_dir = ROOT / 'benchmark' / 'results'
    output_dir.mkdir(exist_ok=True)
    output = output_dir / f'run_{datetime.now():%Y%m%d_%H%M%S_%f}.jsonl'
    report = []
    started = time.monotonic()
    with output.open('x', encoding='utf-8') as log:
        for number, case in enumerate(selected, 1):
            record = {'id': case['id'], 'family': case['family'], 'kind': case['kind'],
                      'question': case['question'], 'expected_rows': case['expected_rows']}
            print(f"\n[{number}/{len(selected)}] {case['id']}: {case['question']}")
            t0 = time.monotonic()
            try:
                generated = generate_sql(case['question'], guide, api_key).strip()
                record['generated'] = generated
                print(generated)
                if case['kind'] == 'unanswerable':
                    record['status'] = 'correct_refusal' if is_refusal(generated) else 'incorrect_refusal'
                    # Unsupported questions are never executed, even if SQL was generated.
                elif is_refusal(generated):
                    record['status'] = 'unexpected_refusal'
                else:
                    try:
                        checked = validate_sql(generated)
                    except Exception as error:
                        record['status'] = 'validation_failed'
                        record['error_type'] = type(error).__name__
                        print(f'SQL 检查未通过：{error}')
                    else:
                        record['checked_sql'] = checked
                        print(f'检查后的 SQL：{checked}')
                        if not args.auto_execute and input('输入 y 执行，其他输入跳过：').strip().lower() != 'y':
                            record['status'] = 'skipped'
                        else:
                            try:
                                columns, actual = execute_sql(checked, password)
                                record['columns'] = columns
                                record['actual_rows'] = [[str(v) if v is not None else None for v in row] for row in actual]
                                record['status'] = 'correct' if compare_rows(actual, case['expected_rows']) else 'incorrect_result'
                                if record['status'] == 'incorrect_result':
                                    print(f"实际：{record['actual_rows']}\n参考：{case['expected_rows']}")
                            except Exception as error:
                                record['status'] = 'query_error'
                                record['error_type'] = type(error).__name__
            except Exception as error:
                record['status'] = 'api_error'
                record['error_type'] = type(error).__name__
            record['elapsed_seconds'] = round(time.monotonic() - t0, 3)
            report.append(record)
            log.write(json.dumps(record, ensure_ascii=False) + '\n')
            log.flush()
            print('结果：' + record['status'])
    graded = [r for r in report if r['status'] != 'skipped']
    answerable = [r for r in graded if r['kind'] == 'answerable']
    unanswerable = [r for r in graded if r['kind'] == 'unanswerable']
    correct = sum(r['status'] in ('correct', 'correct_refusal') for r in graded)
    print(f'\n本次：总通过 {correct}/{len(graded)}，跳过 {len(report)-len(graded)}。')
    print(f"可回答结果正确：{sum(r['status']=='correct' for r in answerable)}/{len(answerable)}。")
    print(f"应拒答且正确拒答：{sum(r['status']=='correct_refusal' for r in unanswerable)}/{len(unanswerable)}。")
    print(f'耗时约 {time.monotonic()-started:.1f} 秒；记录：{output}')
    print('分母包括接口或查询错误；跳过的不计入。比较要求行列顺序匹配。')


if __name__ == '__main__':
    main()
