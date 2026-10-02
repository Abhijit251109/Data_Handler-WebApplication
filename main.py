try:
    from js import document 
    _IN_BROWSER = True
except Exception:
    _IN_BROWSER = False

prompts = {'name': 'Enter name: ', 'employee_id': 'Enter employee ID: ', 'department': 'Enter department: ', 'salary': 'Enter salary: '}

def get_employee_info():
    employee_info = {}
    for key, prompt in prompts.items():
        value = input(prompt).strip()
        if not value:
            raise ValueError(f"{key.replace('_', ' ').capitalize()} cannot be empty.")
        employee_info[key] = value
    return employee_info

def display_employee_info(employee_info):
    print("\nEmployee Information:")
    for key, value in employee_info.items():
        print(f"{key.replace('_', ' ').title()}: {value}")


def save_employee_info(employee_info, filename="employees.txt"):
    # Append mode preserves existing records while ensuring UTF-8 output.
    with open(filename, "a", encoding="utf-8") as file:
        file.write("Employee Information:\n")
        for key, value in employee_info.items():
            file.write(f"{key.replace('_', ' ').title()}: {value}\n")
        file.write("\n")

if __name__ == "__main__" and not _IN_BROWSER:
    employee_info = get_employee_info()
    display_employee_info(employee_info)
    save_employee_info(employee_info)
