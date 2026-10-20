CREATE DATABASE IF NOT EXISTS civic_nest
CHARACTER SET utf8mb4
COLLATE utf8mb4_unicode_ci;

USE civic_nest;


-- =========================================================
-- USERS
-- =========================================================

CREATE TABLE users (
    id INT AUTO_INCREMENT PRIMARY KEY,

    full_name VARCHAR(150) NOT NULL,

    email VARCHAR(150) NOT NULL UNIQUE,

    phone VARCHAR(30),

    password_hash VARCHAR(255) NOT NULL,

    role ENUM('student', 'landlord', 'admin')
        NOT NULL DEFAULT 'student',

    profile_image VARCHAR(255),

    is_verified BOOLEAN NOT NULL DEFAULT FALSE,

    created_at DATETIME NOT NULL,

    updated_at DATETIME NOT NULL
) ENGINE=InnoDB;


-- =========================================================
-- PROPERTIES
-- =========================================================

CREATE TABLE properties (
    id INT AUTO_INCREMENT PRIMARY KEY,

    landlord_id INT NOT NULL,

    title VARCHAR(200) NOT NULL,

    property_type ENUM(
        'hostel',
        'single_room',
        'bedsitter',
        'apartment',
        'house',
        'student_residence',
        'other'
    ) NOT NULL,

    description TEXT NOT NULL,

    location VARCHAR(255) NOT NULL,

    campus VARCHAR(200),

    price DECIMAL(10,2) NOT NULL,

    deposit DECIMAL(10,2),

    distance_from_campus DECIMAL(6,2),

    total_units INT NOT NULL DEFAULT 1,

    occupied_units INT NOT NULL DEFAULT 0,
    
    furnished BOOLEAN DEFAULT FALSE,

    available BOOLEAN DEFAULT TRUE,

    is_verified BOOLEAN DEFAULT FALSE,

    status ENUM(
        'active',
        'unavailable',
        'pending',
        'removed'
    ) DEFAULT 'active',

    created_at DATETIME NOT NULL,

    updated_at DATETIME NOT NULL,

    FOREIGN KEY (landlord_id)
        REFERENCES users(id)
        ON DELETE CASCADE
) ENGINE=InnoDB;


-- =========================================================
-- PROPERTY PHOTOS
-- =========================================================

CREATE TABLE property_images (
    id INT AUTO_INCREMENT PRIMARY KEY,

    property_id INT NOT NULL,

    filename VARCHAR(255) NOT NULL,

    is_cover BOOLEAN DEFAULT FALSE,

    uploaded_at DATETIME NOT NULL,

    FOREIGN KEY (property_id)
        REFERENCES properties(id)
        ON DELETE CASCADE
) ENGINE=InnoDB;


-- =========================================================
-- AMENITIES
-- =========================================================

CREATE TABLE amenities (
    id INT AUTO_INCREMENT PRIMARY KEY,

    name VARCHAR(100) NOT NULL UNIQUE
) ENGINE=InnoDB;


-- =========================================================
-- PROPERTY AMENITIES
-- =========================================================

CREATE TABLE property_amenities (
    property_id INT NOT NULL,

    amenity_id INT NOT NULL,

    PRIMARY KEY (property_id, amenity_id),

    FOREIGN KEY (property_id)
        REFERENCES properties(id)
        ON DELETE CASCADE,

    FOREIGN KEY (amenity_id)
        REFERENCES amenities(id)
        ON DELETE CASCADE
) ENGINE=InnoDB;


-- =========================================================
-- FAVORITES
-- =========================================================

CREATE TABLE favorites (
    id INT AUTO_INCREMENT PRIMARY KEY,

    user_id INT NOT NULL,

    property_id INT NOT NULL,

    created_at DATETIME NOT NULL,

    UNIQUE(user_id, property_id),

    FOREIGN KEY (user_id)
        REFERENCES users(id)
        ON DELETE CASCADE,

    FOREIGN KEY (property_id)
        REFERENCES properties(id)
        ON DELETE CASCADE
) ENGINE=InnoDB;


-- =========================================================
-- PROPERTY INQUIRIES
-- =========================================================

CREATE TABLE inquiries (
    id INT AUTO_INCREMENT PRIMARY KEY,

    student_id INT NOT NULL,

    property_id INT NOT NULL,

    message TEXT NOT NULL,

    status ENUM(
        'new',
        'read',
        'responded',
        'closed'
    ) DEFAULT 'new',

    created_at DATETIME NOT NULL,

    FOREIGN KEY (student_id)
        REFERENCES users(id)
        ON DELETE CASCADE,

    FOREIGN KEY (property_id)
        REFERENCES properties(id)
        ON DELETE CASCADE
) ENGINE=InnoDB;


-- =========================================================
-- REVIEWS
-- =========================================================

CREATE TABLE reviews (
    id INT AUTO_INCREMENT PRIMARY KEY,

    student_id INT NOT NULL,

    property_id INT NOT NULL,

    rating TINYINT NOT NULL,

    comment TEXT,

    created_at DATETIME NOT NULL,

    FOREIGN KEY (student_id)
        REFERENCES users(id)
        ON DELETE CASCADE,

    FOREIGN KEY (property_id)
        REFERENCES properties(id)
        ON DELETE CASCADE,

    CHECK (rating >= 1 AND rating <= 5),

    UNIQUE(student_id, property_id)
) ENGINE=InnoDB;


-- =========================================================
-- ROOMMATE PROFILES
-- =========================================================

CREATE TABLE roommate_profiles (
    id INT AUTO_INCREMENT PRIMARY KEY,

    user_id INT NOT NULL UNIQUE,

    campus VARCHAR(200),

    preferred_location VARCHAR(255),

    budget_min DECIMAL(10,2),

    budget_max DECIMAL(10,2),

    accommodation_type VARCHAR(100),

    move_in_date DATE,

    people_needed INT DEFAULT 1,

    gender_preference ENUM(
        'any',
        'male',
        'female'
    ) DEFAULT 'any',

    lifestyle_preferences TEXT,

    study_preferences TEXT,

    bio TEXT,

    is_active BOOLEAN DEFAULT TRUE,

    created_at DATETIME NOT NULL,

    updated_at DATETIME NOT NULL,

    FOREIGN KEY (user_id)
        REFERENCES users(id)
        ON DELETE CASCADE
) ENGINE=InnoDB;


-- =========================================================
-- ROOMMATE CONNECTIONS
-- =========================================================

CREATE TABLE roommate_connections (
    id INT AUTO_INCREMENT PRIMARY KEY,

    requester_id INT NOT NULL,

    receiver_id INT NOT NULL,

    status ENUM(
        'pending',
        'accepted',
        'declined',
        'blocked'
    ) DEFAULT 'pending',

    created_at DATETIME NOT NULL,

    UNIQUE(requester_id, receiver_id),

    FOREIGN KEY (requester_id)
        REFERENCES users(id)
        ON DELETE CASCADE,

    FOREIGN KEY (receiver_id)
        REFERENCES users(id)
        ON DELETE CASCADE
) ENGINE=InnoDB;


-- =========================================================
-- PROPERTY REPORTS
-- =========================================================

CREATE TABLE property_reports (
    id INT AUTO_INCREMENT PRIMARY KEY,

    reporter_id INT NOT NULL,

    property_id INT NOT NULL,

    reason ENUM(
        'fake_listing',
        'wrong_price',
        'already_occupied',
        'misleading_photos',
        'suspicious_landlord',
        'duplicate_listing',
        'other'
    ) NOT NULL,

    details TEXT,

    status ENUM(
        'pending',
        'reviewed',
        'resolved',
        'dismissed'
    ) DEFAULT 'pending',

    created_at DATETIME NOT NULL,

    FOREIGN KEY (reporter_id)
        REFERENCES users(id)
        ON DELETE CASCADE,

    FOREIGN KEY (property_id)
        REFERENCES properties(id)
        ON DELETE CASCADE
) ENGINE=InnoDB;


-- =========================================================
-- DEFAULT AMENITIES
-- =========================================================

INSERT INTO amenities (name) VALUES
('Wi-Fi'),
('Water'),
('Electricity'),
('Security'),
('Parking'),
('Laundry'),
('Kitchen'),
('Hot Shower'),
('Furnished'),
('Study Area'),
('Backup Generator'),
('CCTV');