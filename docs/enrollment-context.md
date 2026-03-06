# Enrollment Context — Student Registration Data

## Purpose

Student enrollment data represents the foundational dataset for tracking a student's relationship with the educational institution. It captures the lifecycle of registration events — from initial enrollment through transfers, withdrawals, and re-enrollments — and serves as the authoritative source for determining a student's active status at any campus on any given date.

## Registration Lifecycle

The enrollment registration lifecycle follows a well-defined sequence:

1. **Initial Enrollment** — A student is registered for the first time in the district. A unique Student ID is assigned and persists across all subsequent enrollments.
2. **Campus Assignment** — The student is associated with a specific campus and grade level for a given academic year.
3. **Active Attendance** — During the enrollment period, attendance records are generated daily and linked to the enrollment record.
4. **Transfer** — When a student moves to a different campus within the district, the current enrollment is closed and a new enrollment record is created at the receiving campus.
5. **Withdrawal** — If a student leaves the district, the enrollment record is closed with a withdrawal code indicating the reason.
6. **Re-Enrollment** — A previously withdrawn student may return to the district. A new enrollment record is created referencing the original Student ID to preserve longitudinal continuity.

## Relationship to Student Identity

Each enrollment record is linked to a canonical student identity through the `StudentId` field. This identifier is assigned at first enrollment and remains stable across all campuses, academic years, and source systems. It enables cross-system joins between enrollment, attendance, grades, and assessment data.

## Relationship to Academic History

Enrollment records anchor the student's academic timeline. Grades, course completions, and assessment results are all scoped to a specific enrollment period. Without a valid enrollment record, downstream academic data cannot be attributed to a student at a campus for a given term.

## Data Quality Considerations

- Duplicate enrollment records (same student, same campus, overlapping dates) indicate data integrity issues that must be resolved before downstream reporting.
- Enrollment gaps (periods where a student has no active enrollment) may signal unreported transfers or data entry omissions.
- The `EnrollDate` field is the authoritative start date; systems that derive enrollment status from attendance records alone may produce inaccurate results.

## Source Systems

Enrollment data originates from both **Synergy** (Student Information System) and **Zipline** (Assessment and Enrollment Platform). Both systems export enrollment metadata conforming to the platform's frozen contract schemas.
