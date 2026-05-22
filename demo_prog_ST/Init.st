

PROGRAM _INIT
	svgContent := '<text class="cText" text-anchor="start" font-family="Helvetica, Arial, sans-serif" font-size="25" y="380" x="200" stroke-width="0" stroke="#000" fill="#ff8800">Injection Molding Machine <animate id="a1" attributeType="XML" attributeName="fill" begin="0;a2.end" from="orange" to="black" dur="2s"/> <animate id="a2" attributeType="XML" attributeName="fill" begin="a1.end" from="black" to="orange" dur="2s"/> <animate id="a3" attributeType="XML" attributeName="x" begin="0;a4.end" from="200" to="1000" dur="5s"/> <animate id="a4" attributeType="XML" attributeName="x" begin="a3.end" from="1000" to="200" dur="5s"/> </text>';
	
	svgFilePath := 'Media/Animation/SGM small.svg';

	transitionTime := 1000;
	
	transform;
	
	
	transformLift;

END_PROGRAM