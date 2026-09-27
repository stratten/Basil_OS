"use client";

import React from 'react';

export interface ProductData {
  id: string;
  name: string;
  price: string;
  rating: number;
  reviewCount: string;
  description: string;
  imageColor: string; // Color for placeholder image
  badge?: string; // e.g., "Best Seller", "Amazon's Choice"
}

interface MockAmazonProductPageProps {
  product: ProductData;
  className?: string;
}

/**
 * MockAmazonProductPage - A simplified mock of an Amazon product listing page.
 * Shows product image, title, price, rating, and add to cart button.
 */
const MockAmazonProductPage = ({
  product,
  className = "",
}: MockAmazonProductPageProps) => {
  // Generate star rating display
  const renderStars = (rating: number) => {
    const fullStars = Math.floor(rating);
    const hasHalfStar = rating % 1 >= 0.5;
    const emptyStars = 5 - fullStars - (hasHalfStar ? 1 : 0);
    
    return (
      <div className="flex items-center gap-0.5">
        {[...Array(fullStars)].map((_, i) => (
          <svg key={`full-${i}`} className="w-3 h-3 text-amber-400" fill="currentColor" viewBox="0 0 20 20">
            <path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z" />
          </svg>
        ))}
        {hasHalfStar && (
          <svg className="w-3 h-3 text-amber-400" fill="currentColor" viewBox="0 0 20 20">
            <defs>
              <linearGradient id="half">
                <stop offset="50%" stopColor="currentColor" />
                <stop offset="50%" stopColor="#D1D5DB" />
              </linearGradient>
            </defs>
            <path fill="url(#half)" d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z" />
          </svg>
        )}
        {[...Array(emptyStars)].map((_, i) => (
          <svg key={`empty-${i}`} className="w-3 h-3 text-gray-300" fill="currentColor" viewBox="0 0 20 20">
            <path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z" />
          </svg>
        ))}
      </div>
    );
  };

  return (
    <div className={`bg-white h-full overflow-y-auto ${className}`}>
      {/* Amazon-style header bar */}
      <div className="bg-[#232f3e] px-3 py-1.5 flex items-center gap-2">
        <span className="text-white font-bold text-sm">emazon</span>
        <div className="flex-1 flex items-stretch">
          <input 
            type="text" 
            placeholder="Search" 
            className="w-full px-2 py-1 rounded-l text-xs bg-white"
            readOnly
          />
          <button className="bg-amber-400 px-2 rounded-r flex items-center">
            <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
          </button>
        </div>
      </div>

      {/* Product content */}
      <div className="p-3 flex gap-3">
        {/* Product image placeholder */}
        <div 
          className="w-20 h-20 rounded flex-shrink-0 flex items-center justify-center"
          style={{ backgroundColor: product.imageColor }}
        >
          <svg className="w-8 h-8 text-white/70" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4" />
          </svg>
        </div>

        {/* Product details */}
        <div className="flex-1 min-w-0">
          {/* Badge */}
          {product.badge && (
            <span className="inline-block px-1.5 py-0.5 bg-amber-100 text-amber-800 text-[9px] font-medium rounded mb-1">
              {product.badge}
            </span>
          )}
          
          {/* Title */}
          <h3 className="text-xs font-medium text-blue-600 hover:text-orange-600 line-clamp-2 cursor-pointer">
            {product.name}
          </h3>
          
          {/* Rating */}
          <div className="flex items-center gap-1 mt-1">
            {renderStars(product.rating)}
            <span className="text-[10px] text-blue-600">{product.reviewCount}</span>
          </div>
          
          {/* Price */}
          <div className="mt-1">
            <span className="text-lg font-medium">{product.price}</span>
          </div>
          
          {/* Prime badge */}
          <div className="flex items-center gap-1 mt-1">
            <span className="text-[9px] font-bold text-blue-700 bg-blue-50 px-1 rounded">prime</span>
            <span className="text-[9px] text-gray-500">FREE delivery</span>
          </div>
        </div>
      </div>

      {/* Description */}
      <div className="px-3 pb-2">
        <p className="text-[10px] text-gray-600 line-clamp-2">{product.description}</p>
      </div>

      {/* Add to Cart button */}
      <div className="px-3 pb-3">
        <button className="w-full py-1.5 bg-amber-400 hover:bg-amber-500 rounded-full text-xs font-medium transition-colors">
          Add to Cart
        </button>
      </div>
    </div>
  );
};

export default MockAmazonProductPage;

// Pre-defined parody products
export const PARODY_PRODUCTS: ProductData[] = [
  {
    id: 'revolve',
    name: 'Revolve Triple Oxi Upholstery & Fabric Stain Remover, 22 fl oz Spray',
    price: '$8.99',
    rating: 4.5,
    reviewCount: '12,847',
    description: 'Powerful enzyme-based formula removes tough stains including red wine, coffee, and pet accidents from upholstery and fabric furniture.',
    imageColor: '#E91E63',
    badge: 'Best Seller',
  },
  {
    id: 'mr-mean',
    name: 'Mr. Mean Multi-Surface Cleaner with Febreze Meadows & Rain, 45 fl oz',
    price: '$12.49',
    rating: 4.7,
    reviewCount: '8,234',
    description: 'All-purpose cleaner that cuts through grease and grime on virtually any surface while leaving a fresh scent.',
    imageColor: '#4CAF50',
    badge: "Emazon's Choice",
  },
  {
    id: 'oxyfresh',
    name: 'OxyFresh Versatile Stain Remover Powder, 3 lb Tub - Free of Dyes & Perfumes',
    price: '$14.99',
    rating: 4.6,
    reviewCount: '23,456',
    description: 'Oxygen-powered stain fighter works on laundry, carpet, and upholstery. Safe for colors and all washable fabrics.',
    imageColor: '#2196F3',
  },
];
