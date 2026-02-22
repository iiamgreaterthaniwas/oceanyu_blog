/*
  用户系统数据库迁移脚本
  在原有 oceanyu_blog 数据库基础上，新增用户表并关联博客和评论表
*/

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- ----------------------------
-- 新增用户表
-- ----------------------------
CREATE TABLE IF NOT EXISTS `user` (
  `id` int NOT NULL AUTO_INCREMENT,
  `username` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL UNIQUE,
  `password_hash` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `email` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL UNIQUE,
  `avatar_path` varchar(500) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL,
  `bio` varchar(500) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT '这个人很神秘，什么都没有留下~',
  `role` enum('admin','user') CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'user',
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`) USING BTREE
) ENGINE = InnoDB AUTO_INCREMENT = 1 CHARACTER SET = utf8mb4 COLLATE = utf8mb4_unicode_ci ROW_FORMAT = DYNAMIC;

-- ----------------------------
-- 为 post 表新增 user_id 字段（关联用户）
-- ----------------------------
ALTER TABLE `post` ADD COLUMN IF NOT EXISTS `user_id` int NULL DEFAULT NULL;
ALTER TABLE `post` ADD CONSTRAINT `post_ibfk_1` FOREIGN KEY IF NOT EXISTS (`user_id`) REFERENCES `user` (`id`) ON DELETE SET NULL ON UPDATE RESTRICT;

-- ----------------------------
-- 为 comment 表新增 user_id 字段（关联用户）
-- ----------------------------
ALTER TABLE `comment` ADD COLUMN IF NOT EXISTS `user_id` int NULL DEFAULT NULL;
ALTER TABLE `comment` ADD CONSTRAINT `comment_ibfk_2` FOREIGN KEY IF NOT EXISTS (`user_id`) REFERENCES `user` (`id`) ON DELETE SET NULL ON UPDATE RESTRICT;

-- ----------------------------
-- 修改 comment 表 author 字段长度（兼容）
-- ----------------------------
ALTER TABLE `comment` MODIFY COLUMN `author` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL;

SET FOREIGN_KEY_CHECKS = 1;
