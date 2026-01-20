# Commerce Project

The Commerce Project is a comprehensive solution designed to efficiently manage store operations. It supports features such as product management, sales, purchases, customer management, income, expense tracking, and report generation. It is built with multi-language support, offering both English and Persian.

## Features

- **Product Management**: Add, edit, delete, and manage products in the store.
- **Sales & Purchases**: Track sales and purchase records to maintain inventory and finances.
- **Customer Management**: Maintain a database of customers with the ability to manage profiles and track transactions.
- **Income & Expense Tracking**: Record and monitor the store's income and expenses.
- **Reporting**: Generate daily, monthly, and custom date-range reports for better decision-making and analytics.
- **Multi-Language Support**: Built with support for **English** and **Persian** for a better user experience.

## Technologies Used

- **Backend Framework**: [Django](https://www.djangoproject.com/) (Python)
- **Frontend Styling**: [Sass](https://sass-lang.com/)
- **Database**: [SQLite 3](https://www.sqlite.org/index.html)

## Installation

To set up the project locally, follow these steps:

### Prerequisites

- [Python](https://www.python.org/) (version 3.8 or higher)
- [SQLite 3](https://www.sqlite.org/index.html)
- [Git](https://git-scm.com/)

### Steps

1. Clone the repository:
   ```bash
   git clone https://github.com/Esmat-Farjad/commerce.git
   cd commerce
   ```

2. Create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows, use `venv\Scripts\activate`
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Set up environment variables:
   Create a `.env` file in the root directory and add the following variables (replace placeholders with your actual values):
   ```
   DEBUG=True
   SECRET_KEY=your_django_secret_key
   ```

5. Apply migrations:
   ```bash
   python manage.py migrate
   ```

6. Run the development server:
   ```bash
   python manage.py runserver
   ```

7. Open the application in your browser at `http://127.0.0.1:8000`.

## Usage

### Running the Application
- **Development Mode**:
  ```bash
  python manage.py runserver
  ```

- **Production Mode**:
  Use a production web server like Gunicorn or deploy using a platform like AWS, Heroku, or DigitalOcean.

### Collect Static Files
Run the following command to collect static files for production:
```bash
python manage.py collectstatic
```

### Running Tests
To run tests, use:
```bash
python manage.py test
```

## Contributing

Contributions are welcome! If you'd like to help improve this project, please open an issue or submit a pull request. Be sure to follow the project's [Code of Conduct](./CODE_OF_CONDUCT.md).

## License

This project is licensed under the [MIT License](./LICENSE).

## Contact

For any questions or feedback, please reach out to:


- **GitHub**: [Esmat-Farjad](https://github.com/Esmat-Farjad)
- **Email**: [your-email@example.com](mailto:your-email@example.com)

---

Thank you for checking out the Commerce Project! 🚀
