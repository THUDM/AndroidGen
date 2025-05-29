import sys
from ..llms import llm_provider
from .judge_prompt import system_prompt, verify_template, example_input, example_output

import re
import os
import json
import sys
import argparse
from tqdm import tqdm
    
def verify(judger, env, task, action_list, state_list):
    
    action_history = '\n'.join(action_list)
    
    last_state = state_list[-1]
    
    query = verify_template % (task, action_history, last_state)
    
    history = [
        {
            "role": "user",
            "content": {
                "text": example_input
            }
        },
        {
            "role": "assistant",
            "content": {
                "text": example_output
            }
        }
    ]
    
    for _ in range(3):
        try:
            output = judger.generate(query, system_prompt=system_prompt, history=history).strip()
        except Exception as e:
            print(e)
            continue
        
        conditions = []
        for condition in output.split('\n'):
            match_contidion = re.match(r'(.+): (-?\d+)', condition)
            if match_contidion:
                conditions.append((match_contidion.group(1).strip(' \n\"'), int(match_contidion.group(2))))
        
        if conditions:
            return -1 not in [step for _, step in conditions], conditions
    
    print(f'Failed to verify the task: {task}, skip it.')
    return None, None

def get_id(record):
    env = record[0]['env']
    if env == 'android':
        return record[0]['app']
    else:
        raise ValueError(f'Unsupported environment: {env}')

def load_data(data_path):
    with open(data_path, 'r') as f:
        record = [json.loads(line) for line in f.readlines()]
    
    env = record[0]['env']
    task = record[0]['instruction']
    init_state = record[0]['app']
    action_list = [step['response'] for step in record]
    state_list = [step['state'] for step in record]
    
    return env, task, init_state, action_list, state_list

def format_example(task, action_list):
    example = f'# A reference example:\n<|user|>\nUser Instruction: {task}'
    for i, action in enumerate(action_list[:20]):
        example += f'\n\n<|user|>\n** Environment State (Omitted) **\n\n<|assistant|>\n{action}'
    
    return example

def run(data_dir, output_path, model_name):
    correct, all = 0, 0
    
    judger = llm_provider(model_name)
    
    retrieval_database = {}
    if os.path.exists(output_path):
        with open(output_path) as f:
            retrieval_database = json.load(f)

    if not os.path.exists(data_dir):
        os.makedirs(data_dir)
    for dir_name in tqdm(os.listdir(data_dir)):
        file_path = os.path.join(data_dir, dir_name, 'record.jsonl')
        if os.path.exists(file_path):
            env, task, init_state, action_list, state_list = load_data(file_path)
            if dir_name in retrieval_database:
                continue
            
            res, conditions = verify(judger, env, task, action_list, state_list)
            if res is None and conditions is None:
                continue
            
            if res:
                correct += 1
            
            # overall task completion
            example = format_example(task, action_list)
            retrieval_database[dir_name] = {
                'env': env,
                'task': task,
                'init_state': init_state,
                'example': example,
                'complete': res,
                'record': os.path.join(data_dir, dir_name),
                'conditions': conditions
            }

            # subgoal completion
            goal_list = []
            for ix, (goal, step) in enumerate(conditions[:-1]):
                if step == -1:
                    break
                
                goal_str = ', '.join(goal_list) + ' and ' + goal if goal_list else goal
                goal_str = goal_str.capitalize()
                
                example = format_example(goal_str, action_list[:step+1])
                retrieval_database[f'{dir_name}-{ix}'] = {
                    'env': env,
                    'task': goal_str,
                    'init_state': init_state,
                    'example': example,
                    'complete': True,
                    'record': os.path.join(data_dir, dir_name),
                    'step': step
                }
                
                goal_list.append(goal)
                    
            with open(output_path, 'w') as f:
                json.dump(retrieval_database, f, ensure_ascii=False, indent=4)
                    
            all += 1

    return f'{correct} / {all}'

if __name__ == '__main__': 
    parser = argparse.ArgumentParser(description='Run judgement')
    parser.add_argument('-d', '--data_dir', type=str, help='Directory of the trace data', default='./episodes')
    parser.add_argument('-o', '--output_path', type=str, help='Directory of the retrieval database', default='./database.json')
    parser.add_argument('-m', '--model_name', type=str, help='Model name of the judger', default='gpt-4o-2024-08-06')
    args = parser.parse_args()
    
    run(args.data_dir, args.output_path, args.model_name)
    